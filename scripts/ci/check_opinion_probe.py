"""
Rules for the datacenter stance probe, checked in CI (.github/workflows/ci.yml).
Run from the repo root: python scripts/ci/check_opinion_probe.py

The probe reads where each agent stands every game hour and the dashboard
graphs it, so two things have to hold:

- A response with no whole number from 1 to STANCE_SCALE in it scores None.
  Every other rating in this codebase falls back to a middling default on a
  parse failure (poignancy returns 4); here that would be a fabricated opinion
  sitting in the graph next to real ones, indistinguishable from an agent that
  is torn.
- The probe reads memory read-only. The only write to last_accessed is inside
  new_retrieve, so a probe that selects by relevance itself and never calls it
  cannot reset the recency clock on what it read. check_retrieval.py proves
  the touch=False half, for the console commands that do retrieve.
- The probe selects its evidence by relevance to the stance question, over age
  bands. new_retrieve's composite of recency, relevance and importance is the
  agent's own priority order and stays untouched for planning and reflection;
  as the observer's selection criterion it left one agent's reading resting on
  5 of its 1,679 memories and withheld 22 readings that had a relevant memory
  in the pool all along.
- The prompt does not hand the model a list of numbers to choose from. With
  anchors spelled out as "1 -- against, 3 -- leans against, 5 -- torn, ...",
  gpt-4o-mini used only those six values across 192 readings and nothing else,
  so a conditional position had to flip between 3 and 7 while the belief behind
  it never moved.
- The probe passes temperature explicitly. ChatGPT_request ignores the
  gpt_param dict every other prompt builds, so without this the readings are
  sampled at the chat_completion default and repeat reads of an unchanged
  memory set disagree with each other.
- Evidence reaches the model oldest-first and dated, or "what this agent
  thinks now" is indistinguishable from "what it thought yesterday".
- The probe is given the agent's name and age, and nothing else about them.
  The full identity stable set carries traits, values, stake, persuadability,
  lifestyle, currently and the daily plan requirement, every one of which lets
  a position be inferred without stating one -- so with them in the prompt a
  reading can come from the description rather than the memories, and it looks
  like a settled baseline instead of a missing measurement. revise_identity
  rewrites two of those fields nightly, which would make the inferred part
  drift on its own in the direction the agent had been reflecting.
- The prompt separates working on the datacenter from wanting it built, and
  treats an unanswered objection as opposition. Without both, the agents who
  deal with the proposal all day -- the engineer, the organiser -- read as its
  strongest supporters no matter what they argue for.
- The prompt and its example output name no sample rating. Whatever number the
  example carries, the model copies it.
- A reading with no relevant memory behind it, or taken while the agent is
  asleep, is withheld with a reason instead of being answered.
"""
import inspect
import os
import re
import sys
import types

BACKEND = os.path.join(os.path.dirname(__file__), "..", "..",
                       "reverie", "backend_server")
BACKEND = os.path.abspath(BACKEND)
# run_gpt_prompt resolves its prompt templates relative to the backend
# directory, the way reverie.py is run.
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

import opinion_probe
from persona.prompt_template import run_gpt_prompt
from persona.prompt_template.run_gpt_prompt import (
  STANCE_SCALE, STANCE_SEPARATOR, parse_stance, stance_iss)

problems = []

# -- A rating is either 1 to STANCE_SCALE, or nothing ------------------------
rated = {
  f"58 {STANCE_SEPARATOR} the jobs would help": (58, "the jobs would help"),
  "58": (58, ""),
  "  100  ": (100, ""),
  "1": (1, ""),
  "57.4 || rounds down": (57, "rounds down"),
}
for raw, expected in rated.items():
  got = parse_stance(raw)
  if got != expected:
    problems.append(f"parse_stance({raw!r}) is {got!r}, expected {expected!r}")

# Out of range, non-numeric, empty, and a model that would rather not answer.
for raw in ["0", "101", "-3", "", None, "neutral", "I'd rather not say",
            "somewhere in the middle || hedging"]:
  score, rationale = parse_stance(raw)
  if score is not None:
    problems.append(f"parse_stance({raw!r}) produced a score of {score}; a "
                    f"response with no usable rating must score None rather "
                    f"than a made-up number")
  if raw and rationale != str(raw).strip():
    problems.append(f"parse_stance({raw!r}) dropped the raw response, so a "
                    f"failed reading can't be told apart from an empty one")

# -- The probe reads memory without marking it as accessed -------------------
# The probe used to call new_retrieve(touch=False), and the rule here was that
# it passed the keyword. It now selects by relevance itself and calls no
# retrieval at all, which is the same invariant held more simply: the only
# write to last_accessed is inside new_retrieve (retrieve.py), so a probe that
# never reaches it cannot reset the recency clock on what it read, with or
# without a keyword. Checked as source text because the call could sit in any
# helper in the module, not only in probe().
with open(os.path.join(BACKEND, "opinion_probe.py"), encoding="utf-8") as f:
  source = f.read()
retrievals = [call for call in re.findall(r"new_retrieve\s*\([^)]*\)", source,
                                          re.S)
              if "touch=False" not in call]
if retrievals:
  problems.append(f"opinion_probe retrieves without touch=False "
                  f"({retrievals[0].split(chr(10))[0]}...), so probing an "
                  f"agent resets the recency clock on the memories it read "
                  f"and changes what that agent retrieves next")

# -- The probe reads the newest memory last, and dated -----------------------
# Retrieval hands back its 30 nodes ranked by score. Fed to the model in that
# order they are a jumble with no trajectory in them.
probe_src = inspect.getsource(opinion_probe.probe)
if "sorted(" not in probe_src or "created" not in probe_src:
  problems.append("opinion_probe.probe no longer sorts the retrieved memories "
                  "by created, so the model cannot tell a memory from an hour "
                  "ago from one from yesterday")
if "strftime" not in probe_src:
  problems.append("opinion_probe.probe no longer dates the statements it "
                  "passes to the model, so 'right now' has no meaning in the "
                  "prompt")

# -- The reading is deterministic --------------------------------------------
stance_src = inspect.getsource(run_gpt_prompt.run_gpt_prompt_datacenter_stance)
if "temperature=" not in stance_src:
  problems.append("run_gpt_prompt_datacenter_stance does not pass temperature, "
                  "so ChatGPT_request falls back to the chat_completion "
                  "default and two reads of the same memories disagree")

# -- The prompt asks for the ends of the scale, without naming values --------
# Chat models soften firm positions unless the extremes are called for. But an
# enumerated list of anchors is worse: the model treats it as the set of legal
# answers and snaps to it, which is what turned a 10-point scale into six.
#
# The path is read out of run_gpt_prompt rather than written here. It used to
# be hardcoded to datacenter_stance_v1.txt, and when the loader moved to v2
# every check below went on passing against a file the probe no longer opened
# -- a guard pointed at a dead file is worse than no guard, because it reports
# that it checked.
match = re.search(r'prompt_template = "([^"]*datacenter_stance[^"]*)"',
                  stance_src)
if not match:
  template, name = "", "datacenter_stance"
  problems.append("run_gpt_prompt_datacenter_stance no longer names its "
                  "prompt template in a literal, so these checks cannot tell "
                  "which prompt the probe is actually sending")
else:
  template = os.path.join(BACKEND, match.group(1))
  name = os.path.basename(template)
try:
  with open(template, encoding="utf-8") as f:
    prompt = f.read()
except OSError:
  prompt = ""
  problems.append(f"{template} is missing")
for phrase in [f"0 to {STANCE_SCALE}", "completely against",
               "completely in support", "Do not round"]:
  if phrase not in prompt:
    problems.append(f"{name} no longer says {phrase!r}, so the model is free "
                    f"to keep every rating near the middle or round it to the "
                    f"nearest 10")
# "<number> --" is the anchor-list shape that caused the snapping.
anchors = re.findall(r"^\s*\d+\s+--", prompt, re.M)
if anchors:
  problems.append(f"{name} lists {len(anchors)} numbered anchors "
                  f"({', '.join(a.strip() for a in anchors)}); the model "
                  f"answers from that list and nothing between")

# -- The probe is told a name and an age, and nothing else -------------------
# Every field below is given a tell-tale value, so anything added back to
# stance_iss shows up here by name instead of having to be noticed in a diff.
if "get_str_iss" in stance_src:
  problems.append("run_gpt_prompt_datacenter_stance passes get_str_iss(), so "
                  "the probe can rate an agent from their traits, values, "
                  "stake and daily plan instead of from their memories")
leaky = ["innate", "learned", "lifestyle", "values", "stake", "persuadability",
         "currently", "daily_plan_req"]
probe_scratch = types.SimpleNamespace(
  name="Tom Whitaker", age=54, **{f: f"<{f}>" for f in leaky})
shown = stance_iss(probe_scratch)
for field in leaky:
  if f"<{field}>" in shown:
    problems.append(f"stance_iss puts {field} in front of the stance probe; a "
                    f"position can be read off it without it ever stating one, "
                    f"and the graph cannot tell that reading from a measured "
                    f"one")
for needed in ["Tom Whitaker", "54"]:
  if needed not in shown:
    problems.append(f"stance_iss no longer tells the model {needed!r}; the "
                    f"retrieved memories name people, so a probe that does "
                    f"not know whose memories these are is rating a stranger")

# -- Being busy with the datacenter is not a position on it ------------------
# Measured over one game day: Elena Chen, the engineer paid to analyse the
# load, finished at 85 of 100 on rationales reading "heavily involved in the
# planning and analysis of the datacenter project, indicating strong support",
# and Aisha Rahman read 75 while hunting the missing water figure to argue
# against it. Both were rated on effort, not on anything they wanted.
for phrase in ["not the same as wanting it built",
               "counts against it while it stands unanswered"]:
  if phrase not in prompt.lower():
    problems.append(f"{name} no longer says {phrase!r}, so an agent who "
                    f"studies or opposes the datacenter full time reads as a "
                    f"supporter of it")

# -- The prompt and the probe agree on how a quoted line looks ---------------
# opinion_probe renders the reserved slots as '<name> said: "<line>"' and the
# prompt tells the model that those lines are the agent's own words and
# outrank the summaries. If either side changes the marker alone, the prompt
# is describing a format that is not in front of it, and the agent's own words
# go back to being weighed as though someone else had written them -- which is
# the whole defect the reserved slots exist to fix.
probe_src = inspect.getsource(opinion_probe.probe)
if 'said: "' not in probe_src:
  problems.append("opinion_probe.probe no longer marks the agent's own spoken "
                  "lines with 'said:', so the prompt cannot tell them apart "
                  "from summaries written about the agent")
for phrase in ["said:", "own quoted words above any summary"]:
  if phrase not in prompt.lower():
    problems.append(f"{name} no longer says {phrase!r}, so the agent's own "
                    f"words are weighed no more heavily than a summary of a "
                    f"conversation they happened to be in")

# -- Spoken lines get reserved slots, not a share of the ranking -------------
# Measured over a game day: own utterances sit at a median cosine of 0.24 to
# the stance question where the statements already in the prompt sit at 0.51,
# because the pool's statements are model-written summaries in the question's
# own register. 61 of 431 beat the weakest statement already in the prompt,
# and for one agent none of 97 did. Ranked against the pool they take no
# slots at all, and the prompt goes back to 2% position-bearing.
if not 0 < opinion_probe.RESERVED_N < opinion_probe.EVIDENCE_N:
  problems.append(f"RESERVED_N is {opinion_probe.RESERVED_N} against "
                  f"EVIDENCE_N {opinion_probe.EVIDENCE_N}; at zero the "
                  f"agent's own words never reach the prompt, and at "
                  f"EVIDENCE_N or more the retrieved memories never do")

# -- The prompt hands the model no number to copy -----------------------------
# The old example output began "23 || ...", and 55 of 184 readings came back as
# exactly 23 while all six values from 20 to 26 held 7 between them.
if "23 ||" in stance_src or "23 || " in prompt:
  problems.append("the stance prompt or its example output offers 23 as a "
                  "sample rating; the model copies it, and the distribution "
                  "spikes on that one integer with empty bins either side")

# -- Readings are withheld rather than invented -------------------------------
# A null score with a reason is a visible gap in the chart. A number produced
# from memories that have nothing to do with the datacenter, or from an agent
# asleep in bed, is indistinguishable from a measured position.
if not 0 < opinion_probe.RELEVANCE_FLOOR < 1:
  problems.append(f"opinion_probe.RELEVANCE_FLOOR is "
                  f"{opinion_probe.RELEVANCE_FLOOR}, which is not a cosine "
                  f"similarity; below the floor the same evidence came back "
                  f"as 'none' one hour and 70 the next")
for helper, why in [
    ("is_asleep", "38% of a measured day's readings were of agents in bed, "
                  "who cannot have learned anything about the datacenter"),
    ("RELEVANCE_FLOOR", "without it a reading with no relevant memory in it "
                        "still produces a confident number"),
    ("collapse", "one conversation arrives as a dozen near-identical "
                 "perception events, which filled up to 80% of the prompt"),
    ("pool_relevance", "the probe would be back to selecting evidence by "
                       "new_retrieve's composite, which ranks a fresh thought "
                       "about lunch above the agent's most relevant memory: "
                       "22 of 31 withheld readings held a memory above the "
                       "floor that the composite never offered"),
    ("allocate", "relevance alone has no time term, so on a long run the best "
                 "EVIDENCE_N collapse onto whichever period the agent "
                 "discussed this most and the line reports a position the "
                 "agent has since moved off")]:
  if helper not in probe_src:
    problems.append(f"opinion_probe.probe no longer uses {helper}: {why}")

# -- Age bands cover every statement, and total the slots they are given -----
if sum(n for _, _, n in opinion_probe.BANDS) != (opinion_probe.EVIDENCE_N
                                                 - opinion_probe.RESERVED_N):
  problems.append(f"opinion_probe.BANDS allocate "
                  f"{sum(n for _, _, n in opinion_probe.BANDS)} slots against "
                  f"the {opinion_probe.EVIDENCE_N - opinion_probe.RESERVED_N} "
                  f"left after RESERVED_N; over-allocating lets one band take "
                  f"slots banding exists to reserve for another, and "
                  f"under-allocating leaves slots no band can ever fill")
if opinion_probe.BANDS[-1][1] is not None:
  problems.append("the oldest band in opinion_probe.BANDS has an upper age "
                  "limit, so a memory older than it falls in no band and the "
                  "agent's earliest position on the datacenter -- the one a "
                  "move is measured against -- can never be shown")
if not 0 < opinion_probe.RECENT_UTTERANCE_N < opinion_probe.RESERVED_N:
  problems.append(f"RECENT_UTTERANCE_N is "
                  f"{opinion_probe.RECENT_UTTERANCE_N} against RESERVED_N "
                  f"{opinion_probe.RESERVED_N}; at zero a conversation the "
                  f"agent just had need never reach the prompt, and at "
                  f"RESERVED_N relevance stops choosing any quote at all")
if opinion_probe.PER_TIMESTAMP_N <= 0:
  problems.append("opinion_probe.PER_TIMESTAMP_N is not positive, so no "
                  "statement could be shown at all")
if opinion_probe.EVIDENCE_N <= 0:
  problems.append("opinion_probe.EVIDENCE_N is not positive, so ratings would "
                  "be based on no memories at all")
if STANCE_SCALE < 100:
  problems.append(f"STANCE_SCALE is {STANCE_SCALE}; below 100 there is no room "
                  f"between 'leans against' and 'leans in support' for a "
                  f"conditional position to rest, and the line flips instead")

for p in problems:
  print(p)
print(f"opinion probe rules checked, {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
