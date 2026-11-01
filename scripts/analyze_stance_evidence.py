"""
What the stance graph's readings were actually based on.

Run from the repo root:
  python3 scripts/analyze_stance_evidence.py                 # every run with readings
  python3 scripts/analyze_stance_evidence.py <sim> [<sim>..]

Each row in experiment/opinions.jsonl records the node ids its rating came
from. This resolves them against each persona's nodes.json and answers the
question a score alone cannot: is the line measuring what the agent has come
to think, or re-reading what it was seeded with?

The reason that is in doubt is new_retrieve. It ranks every event and thought
the agent has ever had on recency + relevance + importance, equally weighted,
and returns its best EVIDENCE_N -- its own ranking has no relevance floor in
it, and nothing is ever evicted from the pool. Whisper seeds are highly
relevant and highly poignant, so they win slots every hour of every day.
(opinion_probe applies RELEVANCE_FLOOR afterwards, to decide whether the
reading is worth making at all; it does not change which nodes are ranked.) The two thoughts written
after a conversation (reflect.py) and the chat-linked event (perceive.py) are
the only way a conversation can move a rating, and they have to beat those
seeds to be seen at all.

So three things matter per reading, and none of them is the score:

  seed share    -- how much of the evidence is the original whisper seeding.
                   Flat and high across a multi-day run means the instrument
                   is anchored to the prior, and a flat line proves nothing.
  evidence age  -- how far back the evidence reaches. If the newest piece is
                   always hours old, nothing recent is reaching the probe.
  convo nodes   -- whether chat events and post-conversation thoughts appear
                   at all. Read this against the convos column, never on its
                   own: an agent who never spoke to anyone has nothing to cite,
                   and zero citations there means the run was short, not that
                   the channel is broken. Read it against the quote column
                   too -- spoken lines reach the prompt on their own reserved
                   slots and are not cited node ids, so an agent can be at
                   zero in both chat and plan with its conversations arriving
                   intact.

Seed share is exact: whisper thoughts are the nodes created at the earliest
timestamp in memory, before the first step. The datacenter column is keyword
matched and so is only a rough count -- it is there to be sanity-checked
against the seed share, not quoted.

Two further things this reports, both from measuring a full game day:

  anchoring   55 of 184 readings came back as exactly 23 -- the number the
              prompt's example output used to carry -- while all six values
              from 20 to 26 held 7 between them. A measurement does not pile
              30% of its mass on one integer with empty bins either side, so
              the mode's share is checked on every run.
  withheld    the probe declines to rate an agent asleep for the whole hour,
              one with no memory yet, or one whose closest memory falls below
              opinion_probe.RELEVANCE_FLOOR, and records which. Those are
              deliberate gaps and are counted apart from the readings where
              the model was asked and answered unusably. The labels are
              printed as logged, so a run predating the asleep_night /
              asleep_daytime split still reads correctly.
"""
import collections
import glob
import json
import os
import statistics
import sys

STORAGE = os.path.join("environment", "frontend_server", "storage")
# Rough, and only used for the "dc" column. A reading whose evidence has none
# of these in it had nothing to rate from.
DC_WORDS = ("datacenter", "data center", "vanta", "megawatt", "substation")


def read_jsonl(path):
  with open(path, encoding="utf-8") as f:
    return [json.loads(line) for line in f if line.strip()]


def load_memory(sim):
  """{persona: (nodes_by_id, seed_ids)} for one run.

  Nodes are read from the saved end-of-run memory, which is safe because
  associative memory only ever appends -- a node cited by a reading at step
  360 is still there at the end under the same id.
  """
  out = {}
  pattern = os.path.join(STORAGE, sim, "personas", "*", "bootstrap_memory",
                         "associative_memory", "nodes.json")
  for path in glob.glob(pattern):
    name = path.split(os.sep)[-4]
    with open(path, encoding="utf-8") as f:
      nodes = json.load(f)
    if not nodes:
      continue
    # The whisper seeding runs before the first step, so every seeded thought
    # shares the run's opening timestamp -- that is what identifies them,
    # rather than anything stored on the node itself.
    first = min(n["created"] for n in nodes.values())
    seeds = {i for i, n in nodes.items()
             if n["created"] == first and n["type"] == "thought"}
    out[name] = (nodes, seeds)
  return out


def load_conversations(sim):
  """{persona: conversations they took part in}, from the same log the chart's
  conversation markers are drawn from. Without this the citation counts below
  are unreadable: nothing cited looks identical whether the channel failed or
  the agent simply never spoke to anybody."""
  path = os.path.join(STORAGE, sim, "experiment", "conversations.jsonl")
  per = collections.Counter()
  if os.path.exists(path):
    for row in read_jsonl(path):
      for speaker in row.get("speakers", []):
        per[speaker] += 1
  return per


def classify(node, persona):
  """Which channel a cited node reached the probe through."""
  if node["type"] == "event" and node.get("filling"):
    # perceive.py gives a chat event the chat node's id as its filling; a
    # plain observation has none. The transcript itself is never retrievable.
    return "chat_event"
  if node["type"] == "thought":
    if node["description"].startswith(f"For {persona}'s planning:"):
      return "planning"  # reflect.py, written straight after a conversation
    return "thought"
  return "event"


def analyze(sim):
  opinions = os.path.join(STORAGE, sim, "experiment", "opinions.jsonl")
  if not os.path.exists(opinions):
    return False
  rows = read_jsonl(opinions)
  memory = load_memory(sim)
  if not rows or not memory:
    return False
  convos = load_conversations(sim)

  print(f"\n=== {sim} ===")
  print(f"{len(rows)} readings, {len(memory)} personas with saved memory")

  per_agent = collections.defaultdict(lambda: {
    "scores": [], "gaps": 0, "seed": [], "dc": [], "newest": [],
    "channels": collections.Counter(), "missing": 0, "quoted": 0})

  for row in rows:
    name = row.get("name")
    if name not in memory:
      continue
    nodes, seeds = memory[name]
    a = per_agent[name]
    score = row.get("score")
    if score is None:
      a["gaps"] += 1
    else:
      a["scores"].append(int(score))

    # Spoken lines reach the prompt without being cited node ids: they are
    # drawn from seq_chat's filling, which <evidence> never names. Counting
    # them is what keeps an agent whose conversations arrived this way from
    # being reported as a dropped channel.
    a["quoted"] += (row.get("quoted") or {}).get("n") or 0

    cited = [i for i in (row.get("evidence") or [])]
    found = [i for i in cited if i in nodes]
    a["missing"] += len(cited) - len(found)
    if not found:
      continue
    a["seed"].append(sum(i in seeds for i in found) / len(found))
    a["dc"].append(sum(
      any(w in nodes[i]["description"].lower() for w in DC_WORDS)
      for i in found))
    # node_count rises monotonically, so the largest cited id is the newest
    # thing the probe saw and the total is how far behind the run it was.
    a["newest"].append(max(nodes[i]["node_count"] for i in found)
                       / max(n["node_count"] for n in nodes.values()))
    for i in found:
      a["channels"][classify(nodes[i], name)] += 1

  hdr = (f"{'agent':<18}{'n':>4}{'gaps':>6}{'score':>12}"
         f"{'seed%':>7}{'dc/30':>7}{'newest':>8}"
         f"{'convos':>8}{'chat':>6}{'plan':>6}{'quote':>7}  channel")
  print(hdr)
  print("-" * len(hdr))
  totals = collections.Counter()
  silent = []
  for name in sorted(per_agent):
    a = per_agent[name]
    totals.update(a["channels"])
    span = (f"{a['scores'][0]}->{a['scores'][-1]}" if a["scores"] else "--")
    seed = f"{100 * statistics.fmean(a['seed']):.0f}" if a["seed"] else "--"
    dc = f"{statistics.fmean(a['dc']):.1f}" if a["dc"] else "--"
    newest = f"{100 * statistics.fmean(a['newest']):.0f}%" if a["newest"] else "--"
    spoke = convos[name]
    reached = (a["channels"]["chat_event"] + a["channels"]["planning"]
               + a["quoted"])
    if not spoke:
      channel = "no convos"  # nothing to reach the probe; not a failure
    elif reached:
      channel = "ok"
    else:
      channel = "DROPPED"
      silent += [name]
    print(f"{name:<18}{len(a['scores']) + a['gaps']:>4}{a['gaps']:>6}"
          f"{span:>12}{seed:>7}{dc:>7}{newest:>8}{spoke:>8}"
          f"{a['channels']['chat_event']:>6}{a['channels']['planning']:>6}"
          f"{a['quoted']:>7}  {channel}")

  print(f"\nevidence by channel: {dict(totals)}")
  missing = sum(a["missing"] for a in per_agent.values())
  if missing:
    print(f"note: {missing} cited node ids were not in the saved memory")

  # -- Gaps the probe chose, against gaps it fell into ------------------------
  withheld = collections.Counter(
    r.get("withheld") or "model gave no usable rating"
    for r in rows if r.get("score") is None)
  if withheld:
    print("\nwithheld readings: " + ", ".join(
      f"{reason} {n}" for reason, n in withheld.most_common()))
    unusable = withheld["model gave no usable rating"]
    if unusable:
      print(f"  -> {unusable} of those are not a decision the probe made: the "
            f"model was asked and answered unusably three times over.")

  # -- Is the model answering, or reaching for a number it was shown? --------
  scores = [r["score"] for r in rows if r.get("score") is not None]
  if scores:
    value, count = collections.Counter(scores).most_common(1)[0]
    near = sum(scores.count(v) for v in range(value - 3, value + 4)
               if v != value)
    print(f"\nmost common reading: {value}, {count} of {len(scores)} "
          f"({100 * count / len(scores):.0f}%); the six values either side of "
          f"it hold {near}")
    if count > len(scores) / 5 and count > 3 * max(near, 1):
      print(f"  -> {value} is an anchor, not a measurement. Check that it is "
            f"not printed anywhere in datacenter_stance_v1.txt or in the "
            f"example_output of run_gpt_prompt_datacenter_stance.")

  # The two findings that decide whether the graph can show belief change.
  seeds_all = [s for a in per_agent.values() for s in a["seed"]]
  if seeds_all:
    mean_seed = 100 * statistics.fmean(seeds_all)
    print(f"\nseed share across all readings: {mean_seed:.0f}%")
    if mean_seed > 50:
      print("  -> over half of every rating rests on the opening whisper "
            "seeding. A flat line here is the instrument, not the agents.")
  convo = totals["chat_event"] + totals["planning"]
  quoted = sum(a["quoted"] for a in per_agent.values())
  spoke = sum(1 for n in per_agent if convos[n])
  print(f"conversation-derived evidence cited {convo} times "
        f"({100 * convo / max(sum(totals.values()), 1):.0f}% of all evidence), "
        f"plus {quoted} lines quoted directly; "
        f"{spoke}/{len(per_agent)} agents spoke to anyone")
  if silent:
    print(f"  -> {', '.join(silent)} held conversations that reached no "
          f"rating through any channel -- neither a cited chat node nor a "
          f"quoted line. That is the channel failing. It is not crowding-out: "
          f"relevance now selects the evidence rather than vetoing it, so the "
          f"pool's closest memory is always shown; look at whether "
          f"opinion_probe.collapse is folding away distinct statements before "
          f"suspecting EVIDENCE_N.")
  elif spoke < len(per_agent):
    print("  -> every agent who spoke had it cited. The agents with nothing "
          "cited never spoke, so this run is too short to say whether "
          "conversations move the line -- it is not evidence of a problem.")
  return True


def main(argv):
  sims = argv or sorted(
    p.split(os.sep)[-3] for p in
    glob.glob(os.path.join(STORAGE, "*", "experiment", "opinions.jsonl")))
  if not sims:
    print(f"no runs with experiment/opinions.jsonl under {STORAGE}")
    return 1
  if not sum(analyze(sim) for sim in sims):
    print("nothing to analyze")
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
