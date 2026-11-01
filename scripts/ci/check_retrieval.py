"""
Memory retrieval and reflection rules checked in CI (.github/workflows/ci.yml).
Run from the repo root: python scripts/ci/check_retrieval.py

These guard the scoring behaviour described in the generative agents paper,
each of which was wrong or divergent at some point:

- Recency decays over sandbox game hours since a node was last accessed, so a
  just-retrieved memory scores highest. It used to be assigned by position in
  the candidate list, which ranked the *oldest* memory as the most recent.
- Recency therefore does not depend on the order nodes are passed in.
- Retrieval weights the three components equally.
- Reflection draws its focal points from the 100 most recently created
  records, skipping idle ones. The window used to be a counter that tallied
  idle events but indexed a list with the idle events removed.
- A retrieval with touch=False leaves last_accessed alone, so the hourly
  stance probe can read memory without resetting the recency clock on what it
  read and changing what the agent retrieves next.
- last_accessed survives a save and reload. It used not to be written out, so
  every resumed or forked run flattened recency across the whole stream; a
  nodes.json from before it was saved still loads, falling back to created.
- Every retrieval run by a console command passes touch=False. Commands are
  the observer's side of the simulation: the dashboard interview retrieves 50
  memories to answer a question, and with the default it would stamp all 50
  and steer what the agent plans and reflects on afterwards.
- Each reflection is logged once, outside the insight loop. The stance graph
  marks reflections from that log, and one reflection writes up to fifteen
  thoughts at a single timestamp.
"""
import ast
import contextlib
import datetime
import inspect
import io
import json
import os
import random
import re
import sys
import tempfile
import textwrap

BACKEND = os.path.join(os.path.dirname(__file__), "..", "..",
                       "reverie", "backend_server")
BACKEND = os.path.abspath(BACKEND)
# The cognitive modules resolve their imports and prompt templates relative to
# the backend directory, the way reverie.py is run.
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

from persona.cognitive_modules import reflect, retrieve
from persona.memory_structures.associative_memory import (
  AssociativeMemory, ConceptNode)

problems = []
NOW = datetime.datetime(2023, 2, 13, 12, 0, 0)
DECAY = 0.995


class FakeScratch:
  def __init__(self):
    self.curr_time = NOW
    self.recency_decay = DECAY
    self.recency_w = self.relevance_w = self.importance_w = 1


class FakeMemory:
  def __init__(self, events=(), thoughts=()):
    self.seq_event = list(events)
    self.seq_thought = list(thoughts)
    nodes = self.seq_event + self.seq_thought
    self.embeddings = {n.embedding_key: [1.0, 0.0] for n in nodes}
    self.id_to_node = {n.node_id: n for n in nodes}


class FakePersona:
  def __init__(self, events=(), thoughts=()):
    self.scratch = FakeScratch()
    self.a_mem = FakeMemory(events, thoughts)


def node(node_id, created, last_accessed=None, embedding_key=None):
  n = ConceptNode(node_id, 1, 1, "event", 0, created, None,
                  "subject", "predicate", "object", f"desc {node_id}",
                  embedding_key or f"key {node_id}", 5, set(), None)
  n.last_accessed = last_accessed or created
  return n


# -- Recency decays over game hours since last access ------------------------
# new_retrieve passes its candidates sorted by last_accessed ascending, so the
# oldest comes first. Mirror that here: assigning the score by list position
# ranks the list backwards, and this is the order that exposes it.
hours = [48, 10, 1, 0]
nodes = [node(f"node_{i}", NOW - datetime.timedelta(hours=h))
         for i, h in enumerate(hours)]
scores = retrieve.extract_recency(FakePersona(), nodes)

for h, n in zip(hours, nodes):
  expected = DECAY ** h
  got = scores[n.node_id]
  if abs(got - expected) > 1e-9:
    problems.append(f"recency after {h} game hours is {got:.6f}, "
                    f"expected {DECAY}**{h} = {expected:.6f}")

ranked = [n.node_id for n in sorted(nodes, key=lambda n: -scores[n.node_id])]
freshest_first = [n.node_id for n in reversed(nodes)]
if ranked != freshest_first:
  problems.append(f"recency does not rank the most recently accessed memory "
                  f"highest: ranked {ranked}, expected {freshest_first}")

# -- Recency is independent of the order nodes are passed in -----------------
shuffled = nodes[:]
random.Random(0).shuffle(shuffled)
if retrieve.extract_recency(FakePersona(), shuffled) != scores:
  problems.append("recency changes when the candidate list is reordered, so "
                  "it is scoring list position rather than elapsed time")

# -- Retrieval weights the three components equally --------------------------
with open(os.path.join(BACKEND, "persona", "cognitive_modules",
                       "retrieve.py"), encoding="utf-8") as f:
  weights = re.search(r"^\s*gw = \[([^\]]*)\]", f.read(), re.M)
if not weights:
  problems.append("retrieve.py: could not find the gw retrieval weights")
elif [w.strip() for w in weights.group(1).split(",")] != ["1", "1", "1"]:
  problems.append(f"retrieve.py: retrieval weights are [{weights.group(1)}], "
                  f"expected [1, 1, 1]")

# -- Reflection reads the 100 most recent non-idle records -------------------
total = reflect.FOCAL_POINT_RECORDS + 50
events = [node(f"e_{i}", NOW - datetime.timedelta(hours=total - i))
          for i in range(total)]
# Idle events are stored but must never become focal points, and must not
# consume any of the window.
idle = [node(f"i_{i}", NOW, embedding_key=f"shelf {i} is idle")
        for i in range(25)]
# seq_event is newest-first in the real memory stream.
persona = FakePersona(events=list(reversed(events + idle)))

seen = {}


def capture_focal_pt(persona, statements, n):
  seen["statements"] = statements
  return (["focal point"], None)


original = reflect.run_gpt_prompt_focal_pt
reflect.run_gpt_prompt_focal_pt = capture_focal_pt
try:
  reflect.generate_focal_points(persona, 3)
finally:
  reflect.run_gpt_prompt_focal_pt = original

lines = [l for l in seen.get("statements", "").splitlines() if l.strip()]
if len(lines) != reflect.FOCAL_POINT_RECORDS:
  problems.append(f"reflection built focal points from {len(lines)} records, "
                  f"expected {reflect.FOCAL_POINT_RECORDS}")
expected_keys = [n.embedding_key
                 for n in events[-reflect.FOCAL_POINT_RECORDS:]]
if lines != expected_keys:
  problems.append("reflection did not use the most recently created records: "
                  f"got {lines[:2]}..{lines[-1:]}, "
                  f"expected {expected_keys[:2]}..{expected_keys[-1:]}")
if any("idle" in l for l in lines):
  problems.append("reflection used an idle record as a focal point")

# -- A read-only retrieval must not mark what it read as accessed ------------
# The stance probe reads every agent's memory once a game hour. Recency decays
# from last_accessed, so stamping it would hand the probe's own 30 memories a
# recency score of 1 and let the measurement steer the run it is measuring.
observed = [node(f"o_{i}", NOW - datetime.timedelta(hours=h))
            for i, h in enumerate([48, 10, 1])]
persona = FakePersona(events=observed)
before = {n.node_id: n.last_accessed for n in observed}

patched_embedding = retrieve.get_embedding
retrieve.get_embedding = lambda text: [1.0, 0.0]
try:
  # new_retrieve prints every candidate's score; that noise isn't the point.
  with contextlib.redirect_stdout(io.StringIO()):
    retrieve.new_retrieve(persona, ["where do you stand?"], 30, touch=False)
    untouched = {n.node_id: n.last_accessed for n in observed}
    retrieve.new_retrieve(persona, ["where do you stand?"], 30)
    touched = {n.node_id: n.last_accessed for n in observed}
finally:
  retrieve.get_embedding = patched_embedding

if untouched != before:
  problems.append("new_retrieve(touch=False) changed last_accessed, so an "
                  "observer reading an agent's memory resets the recency "
                  "clock on what it read")
if set(touched.values()) != {NOW}:
  problems.append("new_retrieve no longer marks the nodes it returns as "
                  "accessed, so the agent's own retrievals do not refresh "
                  "recency")

# -- last_accessed survives a save and reload --------------------------------
# It is the only input to recency, and it used not to be written out at all:
# every resumed or forked run reset it to created for every node at once, which
# flattens recency across the whole stream and makes a past ranking
# unreconstructable offline (scripts/sweep_reserved_slots.py documents the
# second half of that). A nodes.json written before it was saved must still
# load, with those nodes falling back to created.
def memory_dir(tmp, nodes=None):
  os.makedirs(tmp, exist_ok=True)
  for name, blank in [("nodes.json", nodes if nodes is not None else {}),
                      ("embeddings.json", {}),
                      ("kw_strength.json", {"kw_strength_event": {},
                                            "kw_strength_thought": {}})]:
    with open(os.path.join(tmp, name), "w") as f:
      json.dump(blank, f)
  return tmp


CREATED = NOW - datetime.timedelta(hours=48)
with tempfile.TemporaryDirectory() as tmp:
  a_mem = AssociativeMemory(memory_dir(os.path.join(tmp, "in")))
  saved = a_mem.add_event(CREATED, None, "s", "p", "o", "desc",
                          {"kw"}, 5, ("key a", [1.0, 0.0]), None)
  saved.last_accessed = NOW
  out = os.path.join(tmp, "out")
  os.makedirs(out)
  a_mem.save(out)

  with open(os.path.join(out, "nodes.json")) as f:
    written = json.load(f)
  reloaded = AssociativeMemory(out).seq_event[0]
  if reloaded.last_accessed != NOW:
    problems.append(f"last_accessed did not survive a save and reload: wrote "
                    f"{NOW}, read back {reloaded.last_accessed}. Recency "
                    f"decays from it, so every resumed run would restart the "
                    f"recency clock on the whole memory stream at once")

  for row in written.values():
    row.pop("last_accessed", None)
  legacy = memory_dir(os.path.join(tmp, "legacy"), written)
  with open(os.path.join(legacy, "embeddings.json"), "w") as f:
    json.dump({"key a": [1.0, 0.0]}, f)
  old = AssociativeMemory(legacy).seq_event[0]
  if old.last_accessed != CREATED:
    problems.append(f"a nodes.json without last_accessed loaded with "
                    f"last_accessed {old.last_accessed} instead of falling "
                    f"back to created {CREATED}, so saved runs from before it "
                    f"was persisted no longer load the way they used to")

# -- Console commands retrieve read-only -------------------------------------
# open_server is the observer's side of the simulation. The dashboard interview
# runs a real retrieval against the question asked, so with the default
# touch=True, asking an agent about the datacenter would hand the 50 memories
# behind its answer a recency score of 1 — the probe's bug above, reached
# through a different door. reverie.py is read as text rather than imported
# because importing it pulls in utils.py, which holds API keys.
with open(os.path.join(BACKEND, "reverie.py"), encoding="utf-8") as f:
  open_server = next((n for n in ast.walk(ast.parse(f.read()))
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "open_server"), None)
if open_server is None:
  problems.append("reverie.py: could not find open_server, so there is no way "
                  "to check how its commands retrieve memory")
else:
  retrievals = [n for n in ast.walk(open_server) if isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "new_retrieve"]
  if not retrievals:
    problems.append("no command in open_server retrieves memory any more; if "
                    "the interview moved, this rule has to move with it")
  for call in retrievals:
    if not any(kw.arg == "touch" and getattr(kw.value, "value", None) is False
               for kw in call.keywords):
      problems.append(f"reverie.py line {call.lineno}: a command in "
                      f"open_server retrieves without touch=False, so running "
                      f"it resets the recency clock on the memories it read "
                      f"and changes what the agent retrieves next")

# -- A reflection is logged once, not once per insight ------------------------
# The dashboard marks reflections on the stance graph from events.jsonl. One
# reflection writes up to fifteen thoughts at the same timestamp, so logging
# per insight would stack fifteen markers on one spot.
def logs_a_reflection(n):
  return (isinstance(n, ast.Call)
          and any(kw.arg == "event_type"
                  and getattr(kw.value, "value", None) == "reflection"
                  for kw in n.keywords))


tree = ast.parse(textwrap.dedent(inspect.getsource(reflect.run_reflect)))
logged = [n for n in ast.walk(tree) if logs_a_reflection(n)]
looped = [n for loop in ast.walk(tree) if isinstance(loop, (ast.For, ast.While))
          for n in ast.walk(loop) if logs_a_reflection(n)]

if not logged:
  problems.append("run_reflect no longer logs a reflection event, so the "
                  "stance graph has no reflection markers to draw")
elif looped:
  problems.append("run_reflect logs its reflection event inside a loop, which "
                  "stacks one marker per insight on a single timestamp instead "
                  "of marking the reflection once")

for p in problems:
  print(p)
print(f"retrieval and reflection rules checked, {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
