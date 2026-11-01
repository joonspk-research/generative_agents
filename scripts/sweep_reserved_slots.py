"""Sweeps RESERVED_N over a finished run, rebuilding each prompt as probe() would.

Run from reverie/backend_server, because that is where the prompt template path
and utils.py resolve from:

  cd reverie/backend_server
  python3 ../../scripts/sweep_reserved_slots.py <sim> 0,5,10,15
  python3 ../../scripts/sweep_reserved_slots.py <sim> 10 --template <path>

This produced every number in §11.5 and §11.6 of
docs/belief-change-cast-and-probe-log.md. It answers two questions that a fresh
run cannot separate: how many evidence slots should be reserved for the agent's
own spoken lines, and whether a prompt change or the evidence change moved a
score. Holding the simulation fixed is the whole point -- `R=0` with the live
template is the no-utterances baseline.

What is faithful and what is not:

  pool statements  the ids the live retrieval actually chose, read off the log,
                   then filtered by the relevance floor and put through the
                   live ranking and allocate(). The ranking itself is now
                   exact, where the composite it replaced could not be
                   recomputed after the fact: cosine needs only embeddings.json
                   and the bands only <created>, both of which are on disk.
                   What stays a compromise is the candidate set -- these are
                   the statements the old selection surfaced, so a sweep sees
                   no more evidence than the original reading had. Rebuilding
                   the full pool is possible now and would change what the
                   sweep compares against the numbers already published in
                   §11.5, which is why it is not done here.
  quoted lines     rebuilt through select_utterances, so the reserved slots
                   split between the latest conversations and the closest
                   earlier ones exactly as they do live, and restricted to
                   conversations that had already happened at that step.
                   Without that cut an early reading would be rated on words
                   the agent had not said yet.
  prompt           the template run_gpt_prompt currently loads, unless
                   --template overrides it. It is read out of the source rather
                   than written here for the reason given in
                   scripts/ci/check_opinion_probe.py: a hardcoded path keeps
                   reporting success against a file the probe no longer opens.
"""
import argparse
import collections
import datetime
import inspect
import json
import os
import re
import statistics
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path[0] is this script's folder, not the working directory, so the
# backend's own imports have to be put on the path explicitly.
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, os.path.join(_ROOT, "reverie", "backend_server"))

import numpy as np
import utils
from replay_stance_prompt import (
  load_nodes, sleeping_through_hour, stub, TIME_FMT)
from opinion_probe import (
  EVIDENCE_N, RELEVANCE_FLOOR, allocate, collapse, embed, select_utterances)
from persona.prompt_template.gpt_structure import (
  ChatGPT_safe_generate_response, generate_prompt)
from persona.prompt_template import run_gpt_prompt
from persona.prompt_template.run_gpt_prompt import (
  STANCE_ABSTAIN, STANCE_QUESTION, STANCE_SCALE, STANCE_SEPARATOR,
  is_stance_abstention, parse_stance, stance_iss)

NODE_FMT = "%Y-%m-%d %H:%M:%S"
EXAMPLE = ("71 || The jobs are real and I have said so at two meetings, "
           "even though the rate question still bothers me.")
INSTRUCTION = (f"The output should be the rating from 1 to {STANCE_SCALE}, or "
               f"'{STANCE_ABSTAIN}' if the memories do not bear on the "
               f"datacenter at all, then ' {STANCE_SEPARATOR} ', then one "
               f"sentence of reasoning in the agent's own voice.")


def live_template():
  """The template path the probe actually opens right now."""
  match = re.search(
    r'prompt_template = "([^"]*datacenter_stance[^"]*)"',
    inspect.getsource(run_gpt_prompt.run_gpt_prompt_datacenter_stance))
  if not match:
    raise SystemExit("could not find the stance template path in "
                     "run_gpt_prompt_datacenter_stance; pass --template")
  return match.group(1)


def cos(a, b):
  a, b = np.array(a), np.array(b)
  return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def utterances_before(nodes, name, when):
  """(created, line) for this agent's own turns said at or before <when>."""
  seen, out = set(), []
  for node in sorted(nodes.values(), key=lambda n: n["created"], reverse=True):
    if node["type"] != "chat" or node["created"] > when:
      continue
    for turn in node["filling"] or []:
      if not isinstance(turn, (list, tuple)) or len(turn) != 2:
        continue
      speaker, line = turn
      line = (line or "").strip()
      if speaker != name or not line or line.lower() in seen:
        continue
      seen.add(line.lower())
      out += [(node["created"], line)]
  return out


def build(row, nodes, embeddings, question, reserved):
  """The statements block the probe would send, at this RESERVED_N."""
  spoken = utterances_before(nodes, row["name"], row["time_iso"])
  # Newest conversation first, which is the order own_utterances hands
  # select_utterances and the order its recent slots are read in.
  spoken.sort(key=lambda pair: pair[0], reverse=True)
  quoted = select_utterances(spoken, reserved)

  cited = [nodes[i] for i in (row.get("evidence") or []) if i in nodes]
  kept = collapse([type("N", (), {"embedding_key": n["embedding_key"],
                                  "node": n})() for n in cited])
  survivors = [k.node for k in kept
               if k.node["embedding_key"] in embeddings
               and cos(embeddings[k.node["embedding_key"]], question)
               >= RELEVANCE_FLOOR]
  # Cosine order, then the bands, as probe() now does -- not the log's order
  # truncated to the budget. Both inputs are on disk, so unlike the composite
  # this is the live ranking and not an approximation of it.
  survivors.sort(key=lambda n: -cos(embeddings[n["embedding_key"]], question))
  banded = [type("N", (), {"created": datetime.datetime.strptime(
                             n["created"], NODE_FMT), "node": n})()
            for n in survivors]
  at = datetime.datetime.strptime(row["time"], TIME_FMT)
  survivors = [n.node for n in
               allocate(banded, at, EVIDENCE_N - len(quoted))[0]]

  lines = [(n["created"], n["embedding_key"]) for n in survivors]
  lines += [(created, f'{row["name"]} said: "{line}"')
            for created, line in quoted]
  block = "\n".join(
    f'{datetime.datetime.strptime(c, NODE_FMT).strftime("%B %d, %H:%M")} -- {t}'
    for c, t in sorted(lines, key=lambda r: r[0]))
  return block, len(survivors), len(quoted)


def ask(template, persona, statements):
  if template == live_template() and "rubric" in template:
    return run_gpt_prompt.run_gpt_prompt_datacenter_stance(persona, statements)[0]
  prompt = generate_prompt(
    [persona.scratch.name, stance_iss(persona.scratch), persona.scratch.name,
     statements, persona.scratch.name,
     persona.scratch.curr_time.strftime("%B %d, %Y, %H:%M")], template)
  seen = {"r": None}

  def validate(r, prompt=""):
    seen["r"] = r
    return parse_stance(r)[0] is not None or is_stance_abstention(r)

  out = ChatGPT_safe_generate_response(
    prompt, EXAMPLE, INSTRUCTION, 3, (None, ""), validate,
    lambda r, prompt="": parse_stance(r), False, temperature=0)
  return out if out is not False else parse_stance(seen["r"])


def summarize(label, scores):
  if not scores:
    print(f"{label:>6}: no readings")
    return
  value, count = collections.Counter(scores).most_common(1)[0]
  print(f"{label:>6}: {len(set(scores))} distinct, "
        f"{100 * sum(1 for s in scores if s % 5 == 0) / len(scores):.0f}% "
        f"mult of 5, mode {value} x{count}, "
        f"above 50: {sum(1 for s in scores if s > 50)}, "
        f"mean {statistics.fmean(scores):.0f}")


def main(sim, template, reserves, per_agent):
  rows = [json.loads(l) for l in open(
    os.path.join(utils.fs_storage, sim, "experiment", "opinions.jsonl"))
    if l.strip()]
  base = os.path.join(utils.fs_storage, sim, "personas")
  ages, memory, embs = {}, {}, {}
  for folder in os.listdir(base):
    with open(os.path.join(base, folder, "bootstrap_memory", "scratch.json"),
              encoding="utf-8") as f:
      ages[folder] = json.load(f).get("age")
    memory[folder] = load_nodes(sim, folder)
    with open(os.path.join(base, folder, "bootstrap_memory",
                           "associative_memory", "embeddings.json"),
              encoding="utf-8") as f:
      embs[folder] = json.load(f)

  # The hour is_asleep samples is 3600 game seconds, which is this many steps.
  with open(os.path.join(utils.fs_storage, sim, "reverie", "meta.json"),
            encoding="utf-8") as f:
    per_step = json.load(f)["sec_per_step"]

  # Both live gates are deterministic, so a row either of them would withhold is
  # skipped rather than re-read: there is no point spending a call on a reading
  # the probe would not make.
  keep = collections.defaultdict(list)
  for row in rows:
    if sleeping_through_hour(sim, row["step"], row["name"], per_step):
      continue
    measured = row.get("relevance") or {}
    shown = measured.get("shown")
    if shown is None:
      shown = measured.get("best")
    if shown is None or shown < RELEVANCE_FLOOR:
      continue
    row["time_iso"] = datetime.datetime.strptime(
      row["time"], TIME_FMT).strftime(NODE_FMT)
    keep[row["name"]] += [row]
  sample = [r for name in sorted(keep) for r in keep[name][-per_agent:]]
  print(f"{len(sample)} readings, last {per_agent} kept per agent, "
        f"template {os.path.basename(template)}\n")

  question = embed(STANCE_QUESTION)
  results = collections.defaultdict(dict)
  for reserved in reserves:
    for row in sample:
      block, n_pool, n_quoted = build(
        row, memory[row["name"]], embs[row["name"]], question, reserved)
      persona = stub(row["name"], ages[row["name"]],
                     datetime.datetime.strptime(row["time"], TIME_FMT))
      score, rationale = ask(template, persona, block)
      results[(row["name"], row["step"])][reserved] = (
        score, rationale, n_pool, n_quoted)
      results[(row["name"], row["step"])]["old"] = row.get("score")

  # Each cell is the score, then (pool statements + quoted lines) behind it.
  print(f"{'agent':<18}{'step':>6}{'old':>5}"
        + "".join(f"{f'R={r}':>18}" for r in reserves))
  for key in sorted(results, key=lambda k: (k[0], k[1])):
    r = results[key]
    cells = "".join(
      f"{f'{r[res][0]} ({r[res][2]}+{r[res][3]})':>18}" for res in reserves)
    print(f"{key[0]:<18}{key[1]:>6}{str(r['old']):>5}{cells}")

  print()
  summarize("old", [r["old"] for r in results.values()
                    if r["old"] is not None])
  for reserved in reserves:
    summarize(f"R={reserved}",
              [r[reserved][0] for r in results.values()
               if r[reserved][0] is not None])

  top = reserves[-1]
  print(f"\n--- rationales at R={top} ---")
  for key in sorted(results, key=lambda k: (k[0], k[1])):
    score, rationale, _, _ = results[key][top]
    print(f"{key[0]:<18}{str(score):>5}  {rationale[:115]}")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("sim", help="simulation code under storage/")
  parser.add_argument("reserves",
                      help="comma-separated RESERVED_N values, e.g. 0,5,10,15")
  parser.add_argument("--template", default=None,
                      help="stance prompt to read through "
                           "(default: whatever run_gpt_prompt loads)")
  parser.add_argument("--per-agent", type=int, default=3,
                      help="readings kept per agent, newest first (default 3)")
  args = parser.parse_args()
  main(args.sim, args.template or live_template(),
       [int(x) for x in args.reserves.split(",")], args.per_agent)
