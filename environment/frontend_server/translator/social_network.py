"""Read-only, reconstructable aggregates of each run's authoritative JSONL logs."""
from collections import OrderedDict
import hashlib
import itertools
import json
import os
import threading


BANDS = (
  ("very_strong_opposition", 0, 19, "Very strong opposition", "#A32834"),
  ("moderate_opposition", 20, 39, "Moderate opposition", "#DD645D"),
  ("slight_opposition", 40, 49, "Slight opposition", "#EFAA86"),
  ("neutral_mixed", 50, 50, "Neutral / genuinely mixed", "#D5B55C"),
  ("slight_support", 51, 60, "Slight support", "#A0CAA0"),
  ("moderate_support", 61, 80, "Moderate support", "#48A276"),
  ("very_strong_support", 81, 100, "Very strong support", "#17754E"),
)
UNRATED = "#9299A4"


def _step(row):
  value = row.get("step")
  return value if type(value) is int and value >= 0 else None


def _conversation(row):
  """The logger writes after generating a complete transcript, not on intent.

  Legacy logs have no ID. Match the logger's deduplication key (step, speakers,
  transcript); neither a changed summary nor a copied fork makes a new chat.
  Keep only a digest, not transcripts, in the long-lived aggregate cache.
  """
  speakers, turns = row.get("speakers"), row.get("utterances")
  if (_step(row) is None or not isinstance(speakers, list)
      or not all(isinstance(n, str) for n in speakers)
      or not isinstance(turns, list) or not turns
      or row.get("completed") is False
      or row.get("status") in ("pending", "started", "in_progress")
      or not all(isinstance(t, (list, tuple)) and len(t) == 2
                 and all(isinstance(s, str) and s.strip() for s in t)
                 for t in turns)):
    return None
  speakers = sorted(set(speakers))
  signature = json.dumps([row["step"], speakers, turns], ensure_ascii=False)
  return {"step": row["step"], "speakers": speakers, "time": row.get("time"),
          "id": str(row["conversation_id"]) if row.get("conversation_id") else None,
          "digest": hashlib.sha256(signature.encode("utf-8")).hexdigest()}


def _opinion(row):
  score, version = row.get("score"), row.get("scoring_version")
  if _step(row) is None or not isinstance(row.get("name"), str):
    return None
  if type(score) is not int:
    return None
  scale = row.get("scale", 10)
  if version == "rubric_v1":
    if scale != 100:
      return None
    displayed = score
  elif version in (None, ""):
    if scale not in (10, 100) or not 1 <= score <= scale:
      return None
    displayed = score if scale == 100 else round((score - 1) * 100 / 9)
  else:
    return None  # Unknown future instruments need an explicit mapping.
  band = next((b for b in BANDS if b[1] <= displayed <= b[2]), None)
  if band is None or (version == "rubric_v1" and row.get("category") != band[0]):
    return None
  return {"name": row["name"], "step": row["step"], "time": row.get("time"),
          "score": score, "scale": scale, "display_score": displayed,
          "category": band[0], "label": band[3], "color": band[4],
          "scoring_version": version or "legacy_direct"}


class _History:
  def __init__(self):
    self.identity = None
    self.offset = 0
    self.stamp = None
    self.rows = []
    self.revision = 0
    self.max_step = 0

  def read(self, path, compact):
    try:
      stat = os.stat(path)
    except OSError:
      if self.identity is not None:
        self.__init__()
      return
    identity = stat.st_dev, stat.st_ino
    stamp = stat.st_mtime_ns, stat.st_size
    if (identity != self.identity or stat.st_size < self.offset
        or (stat.st_size == self.offset and stamp != self.stamp)):
      self.offset, self.rows, self.max_step = 0, [], 0
      self.stamp = None
      self.revision += 1
    self.identity = identity
    if stamp == self.stamp:
      return
    with open(path, "rb") as f:
      f.seek(self.offset)
      while True:
        line = f.readline()
        if not line or not line.endswith(b"\n"):
          break  # A writer may still be appending this record; retry next poll.
        self.offset = f.tell()
        try:
          raw = json.loads(line)
          row = compact(raw) if isinstance(raw, dict) else None
        except (ValueError, TypeError):
          row = None
        if row is not None:
          self.rows.append(row)
          self.max_step = max(self.max_step, row["step"])
        self.revision += 1
    self.stamp = stamp


class NetworkHistory:
  def __init__(self):
    self.conversations, self.opinions = _History(), _History()
    self.key, self.value = None, None

  def summary(self, folder, names, step):
    self.conversations.read(os.path.join(folder, "conversations.jsonl"), _conversation)
    self.opinions.read(os.path.join(folder, "opinions.jsonl"), _opinion)
    # Once all existing records are eligible, clock-only polls reuse the result.
    cutoff = min(step, max(self.conversations.max_step, self.opinions.max_step))
    key = (tuple(names), cutoff, self.conversations.revision, self.opinions.revision)
    if self.key == key:
      return self.value
    nodes = {n: {"name": n, "score": None, "category": None, "label": "Unrated",
                 "color": UNRATED, "time": None, "conversations": 0, "partners": 0}
             for n in names}
    edges, partners, seen, seen_ids = {}, {n: set() for n in names}, set(), set()
    total = 0
    for row in self.conversations.rows:
      if row["step"] > step or row["digest"] in seen:
        continue
      if row["id"] and row["id"] in seen_ids:
        continue
      participants = [n for n in row["speakers"] if n in nodes]
      if len(participants) < 2:
        continue
      seen.add(row["digest"])
      if row["id"]:
        seen_ids.add(row["id"])
      total += 1
      for n in participants:
        nodes[n]["conversations"] += 1
      for a, b in itertools.combinations(participants, 2):
        edge = edges.setdefault((a, b), {"source": a, "target": b, "count": 0,
                                         "step": -1, "time": None})
        edge["count"] += 1
        if row["step"] >= edge["step"]:
          edge.update(step=row["step"], time=row["time"])
        partners[a].add(b)
        partners[b].add(a)
    for row in self.opinions.rows:
      n = nodes.get(row["name"])
      if n is not None and row["step"] <= step and row["step"] >= n.get("step", -1):
        n.update(row)
    for name, n in nodes.items():
      n["partners"] = len(partners[name])
    self.value = {"nodes": list(nodes.values()),
                  "edges": [edges[k] for k in sorted(edges)],
                  "conversations": total,
                  "bands": [{"category": b[0], "min": b[1], "max": b[2],
                             "label": b[3], "color": b[4]} for b in BANDS]}
    self.key = key
    return self.value


_cache = OrderedDict()
_lock = threading.RLock()


def network_summary(sim, names, step):
  # Forking copies experiment files. Read only this run: following its parent
  # too would double-count inherited records and could import later parent work.
  folder = os.path.abspath(os.path.join("storage", sim, "experiment"))
  with _lock:
    history = _cache.setdefault(folder, NetworkHistory())
    _cache.move_to_end(folder)
    while len(_cache) > 8:
      _cache.popitem(last=False)
    return history.summary(folder, names, step)
