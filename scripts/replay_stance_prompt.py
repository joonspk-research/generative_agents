"""Re-reads a finished run's stance readings through the current prompt.

Run from reverie/backend_server, because that is where the prompt template path
and utils.py resolve from:

  cd reverie/backend_server
  python3 ../../scripts/replay_stance_prompt.py <sim> [--limit N] [--out FILE]

Every reading in experiment/opinions.jsonl records the node ids it was based
on, and associative memory only ever appends, so those nodes are all still in
the saved nodes.json under the same ids. That makes the model's input
reconstructable after the fact: feed the same evidence through the new prompt
and the difference in the score is the prompt change, with the simulation held
fixed. A fresh run cannot separate the two.

What this replays and what it cannot:

  prompt wording   replayed exactly.
  example_output   replayed exactly, both live in run_gpt_prompt.
  collapse()       partially. Its deduplication is applied to the recorded
                   evidence, so the repeats it drops are visible. Its other
                   half is not: live, the whole pool is ranked by cosine and a
                   slot freed by deduplication goes to the next distinct
                   statement. Only the cited ids are on disk, so a replayed
                   prompt is short where a live one would be full. The replayed
                   score is therefore based on no more evidence than the
                   original, never less -- the comparison stays fair. Rows
                   logged after the selection field exists carry the rejected
                   candidates and their cosines, which closes this gap for
                   them; rows from before it do not.
  is_asleep        not replayed through persona state; read from the movement
                   snapshots across the hour, which carry act_description.
  RELEVANCE_FLOOR  not replayed; applied to the relevance already recorded on
                   each row.

Both gates are deterministic, so rows they withhold are skipped rather than
re-read -- there is no point spending a call on a reading the new code would
not make. They are counted in the summary.
"""
import argparse
import collections
import json
import os
import statistics
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path[0] is this script's folder, not the working directory, so the
# backend's own modules have to be put on the path by hand. The working
# directory still has to be reverie/backend_server: generate_prompt opens the
# template by a relative path.
sys.path.insert(0, os.path.join(_ROOT, "reverie", "backend_server"))

import utils  # noqa: E402  (reverie/backend_server/utils.py, for fs_storage)
from opinion_probe import (  # noqa: E402
  RELEVANCE_FLOOR, asleep_reason, collapse)
from persona.prompt_template.run_gpt_prompt import (  # noqa: E402
  run_gpt_prompt_datacenter_stance)

import datetime  # noqa: E402

TIME_FMT = "%B %d, %Y, %H:%M:%S"


def load_nodes(sim, name):
  """{node_id: node} for one persona, as plain dicts from the saved memory."""
  path = os.path.join(utils.fs_storage, sim, "personas", name,
                      "bootstrap_memory", "associative_memory", "nodes.json")
  with open(path, encoding="utf-8") as f:
    return json.load(f)


def sleeping_at(sim, step, name, _cache={}):
  """Whether act_description said sleep for this persona at this step.

  movement/<step>.json's description is act_description with the conversation
  and the address appended, so the substring test is the same one is_asleep
  makes against scratch.

  Falls back to the nearest earlier step, because the last probe of a run has
  no movement file: the readings at step 8640 were taken and then the run
  saved, so nothing was ever emitted for that step. Treating a missing file as
  awake quietly un-withholds the midnight readings, which are the ones most
  likely to be of a sleeping agent -- on the measured run that was seven of
  eight.

  Returns None when no snapshot names this persona at all, which the hour
  window needs to tell apart from a snapshot that says awake.
  """
  folder = os.path.join(utils.fs_storage, sim, "movement")
  for candidate in (step, step - 1, step - 2):
    if candidate not in _cache:
      path = os.path.join(folder, f"{candidate}.json")
      if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
          _cache[candidate] = json.load(f).get("persona", {})
      else:
        _cache[candidate] = None
    snapshot = _cache[candidate]
    if snapshot and name in snapshot:
      return "sleep" in (snapshot[name].get("description") or "").lower()
  return None


def sleeping_through_hour(sim, step, name, per_step):
  """is_asleep's hour window, read from movement instead of the schedule.

  The live probe samples f_daily_schedule every ten game minutes and withholds
  only if every task in the hour is sleep. There is no saved schedule to walk
  here -- f_daily_schedule is rewritten nightly and only its final state is on
  disk -- but the movement files are a step-by-step record of what each agent
  was actually doing, which is the better evidence anyway.

  Sampled over 3600 game seconds from the probe's step, so the window follows
  the run's own sec_per_step rather than assuming the hourly cadence that
  opinion_steps happens to be set to. Steps past the end of the run have no
  file and are skipped; if nothing in the window is on disk the single-step
  reading stands.
  """
  stride = max(1, round(600 / per_step))
  seen = [sleeping_at(sim, step + k * stride, name)
          for k in range(round(3600 / per_step / stride))]
  found = [s for s in seen if s is not None]
  return bool(found) and all(found)


def stub(name, age, curr_time):
  """The three fields run_gpt_prompt_datacenter_stance reads off a persona.

  stance_iss takes the name and the age and nothing else, by design (see its
  docstring), and create_prompt_input takes curr_time. Loading eight real
  Personas to supply three strings would also load their embeddings.
  """
  # persona.name as well, which print_run_prompts reads when debug is on.
  return types.SimpleNamespace(
    name=name,
    scratch=types.SimpleNamespace(name=name, age=age, curr_time=curr_time))


def statements_for(row, nodes):
  """The evidence block as probe() would format it, from the recorded ids."""
  cited = [nodes[i] for i in (row.get("evidence") or []) if i in nodes]
  kept = collapse([
    types.SimpleNamespace(embedding_key=n["embedding_key"], node=n)
    for n in cited])
  cited = [k.node for k in kept]
  cited.sort(key=lambda n: n["created"])
  return "\n".join(
    f'{datetime.datetime.strptime(n["created"], "%Y-%m-%d %H:%M:%S").strftime("%B %d, %H:%M")}'
    f' -- {n["embedding_key"]}' for n in cited), len(cited)


def main(argv):
  ap = argparse.ArgumentParser()
  ap.add_argument("sim")
  ap.add_argument("--limit", type=int, default=0,
                  help="replay only the first N kept readings (a dry run)")
  ap.add_argument("--out", default="")
  args = ap.parse_args(argv)

  path = os.path.join(utils.fs_storage, args.sim, "experiment",
                      "opinions.jsonl")
  with open(path, encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
  rows = [r for r in rows if r.get("name")]

  ages = {}
  for folder in os.listdir(os.path.join(utils.fs_storage, args.sim,
                                        "personas")):
    sfile = os.path.join(utils.fs_storage, args.sim, "personas", folder,
                         "bootstrap_memory", "scratch.json")
    with open(sfile, encoding="utf-8") as f:
      ages[folder] = json.load(f).get("age")

  memory = {name: load_nodes(args.sim, name) for name in ages}

  with open(os.path.join(utils.fs_storage, args.sim, "reverie",
                         "meta.json"), encoding="utf-8") as f:
    per_step = json.load(f)["sec_per_step"]

  skipped = collections.Counter()
  kept = []
  for row in rows:
    when = datetime.datetime.strptime(row["time"], TIME_FMT)
    if sleeping_through_hour(args.sim, row["step"], row["name"], per_step):
      skipped[asleep_reason(when)] += 1
      continue
    # <best> where <shown> is missing, which is the whole point of the new
    # selection: the pool's closest memory can no longer be crowded out of
    # the prompt, so the two are the same number and a row the old code
    # withheld for low relevance is replayable from the cosine it recorded.
    measured = row.get("relevance") or {}
    shown = measured.get("shown")
    if shown is None:
      shown = measured.get("best")
    if shown is None:
      # Withheld before anything was measured -- no cosine on disk to apply
      # the floor to. Counted apart from a real below-floor row, because
      # most of these are rows the hour window has just un-withheld and
      # calling them no_relevant_memory would claim a measurement that was
      # never taken.
      skipped["relevance_unrecorded"] += 1
      continue
    if shown < RELEVANCE_FLOOR:
      skipped["no_relevant_memory"] += 1
      continue
    kept += [row]

  print(f"{len(rows)} readings in {args.sim}")
  print(f"the new gates withhold {sum(skipped.values())}: "
        + ", ".join(f"{k} {v}" for k, v in skipped.most_common()))
  print(f"replaying the remaining {len(kept)}"
        + (f", capped at {args.limit}" if args.limit else ""))

  if args.limit:
    kept = kept[:args.limit]

  out = []
  for i, row in enumerate(kept, 1):
    name = row["name"]
    statements, n_evidence = statements_for(row, memory[name])
    persona = stub(name, ages[name],
                   datetime.datetime.strptime(row["time"], TIME_FMT))
    rating = run_gpt_prompt_datacenter_stance(persona, statements, with_metadata=True)[0]
    score, rationale = rating["score"], rating["rationale"]
    record = {"step": row["step"], "time": row["time"], "name": name,
              "old_score": row.get("score"), "new_score": score,
              "old_evidence": len(row.get("evidence") or []),
              "new_evidence": n_evidence,
              "relevance": (row.get("relevance") or {}).get("shown"),
              "rationale": rationale, "category": rating["category"],
              "conditions": rating["conditions"],
              "old_scoring_version": row.get("scoring_version") or "legacy_direct",
              "new_scoring_version": rating["scoring_version"]}
    out += [record]
    print(f"  [{i}/{len(kept)}] {name:<18} step {row['step']:>5}  "
          f"{row.get('score')} -> {score}   "
          f"evidence {len(row.get('evidence') or [])} -> {n_evidence}")

  if args.out:
    with open(args.out, "w", encoding="utf-8") as f:
      for record in out:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(out)} rows to {args.out}")

  report(out)
  return 0


def report(out):
  """Did the prompt change move the readings, and off which values."""
  pairs = [(r["old_score"], r["new_score"]) for r in out
           if r["old_score"] is not None and r["new_score"] is not None]
  if not pairs:
    print("\nnothing comparable")
    return
  moves = [new - old for old, new in pairs]
  print(f"\n{len(pairs)} readings scored under both prompts")
  print(f"mean move {statistics.fmean(moves):+.1f}, "
        f"median {statistics.median(moves):+.0f}, "
        f"range {min(moves):+d} to {max(moves):+d}")
  for label, scores in (("old", [p[0] for p in pairs]),
                        ("new", [p[1] for p in pairs])):
    value, count = collections.Counter(scores).most_common(1)[0]
    near = sum(scores.count(v) for v in range(value - 3, value + 4)
               if v != value)
    print(f"{label}: most common {value}, {count}/{len(scores)} "
          f"({100 * count / len(scores):.0f}%), six values either side {near}")
  dropped = sum(1 for r in out if r["new_score"] is None)
  if dropped:
    print(f"{dropped} replayed readings came back without a usable score")
  # The defect this prompt change was for: a rating above the midpoint that
  # rests on how busy the agent is rather than on which side it is on.
  above = sum(1 for old, new in pairs if old > 50 and new <= 50)
  below = sum(1 for old, new in pairs if old <= 50 and new > 50)
  print(f"crossed down through 50: {above}; crossed up: {below}")
  per = collections.defaultdict(list)
  for r in out:
    per[r["name"]] += [(r["old_score"], r["new_score"])]
  print(f"\n{'agent':<18}{'n':>4}{'old span':>12}{'new span':>12}{'mean move':>11}")
  for name in sorted(per):
    both = [(o, n) for o, n in per[name] if o is not None and n is not None]
    if not both:
      continue
    print(f"{name:<18}{len(both):>4}"
          f"{f'{both[0][0]}->{both[-1][0]}':>12}"
          f"{f'{both[0][1]}->{both[-1][1]}':>12}"
          f"{statistics.fmean(n - o for o, n in both):>+11.1f}")


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
