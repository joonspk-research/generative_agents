# The probe's own-words evidence: decision trail

§11 of [belief-change-cast-and-probe-log.md](belief-change-cast-and-probe-log.md)
records what the probe does now and the numbers behind it. This file records the
part that is harder to recover later: **which questions were asked, which
alternatives were considered, what measurement killed each one, and in what
order.** When a reading looks wrong six months from now, the fastest route is
usually not to re-derive the design — it is to find which decision below is
load-bearing for the symptom and re-run the one measurement that settled it.

Nothing here has been verified against a fresh run. Everything is replay against
`stg-base_the_ville_datacenter_n8_private-2`.

---

## How to re-run any of it

All of these run from `reverie/backend_server` — that is where `utils.py` and
the relative prompt-template path resolve from.

| Question | Command |
|---|---|
| How many slots for spoken lines? Did the prompt or the evidence move a score? | `python3 ../../scripts/sweep_reserved_slots.py <sim> 0,5,10,15` |
| Does a prompt change alone move the scores? | `python3 ../../scripts/sweep_reserved_slots.py <sim> 10 --template <other>` |
| What was a past reading actually based on? | `python3 ../../scripts/analyze_stance_evidence.py <sim>` (from repo root) |
| Does the current prompt change an old reading? | `python3 ../../scripts/replay_stance_prompt.py <sim>` |
| Did any of this break an invariant? | `python3 scripts/ci/check_opinion_probe.py` (and the other four) |

`sweep_reserved_slots.py 10` with no `--template` is the current configuration;
`0` is the no-utterances baseline. Running both in one invocation is what makes
the evidence change separable from the prompt change — a fresh run cannot do
that, because the simulation moves underneath you.

Two caveats that apply to every replay, stated in each script's docstring: pool
statements come from the ids recorded on the reading, because `new_retrieve`'s
composite ranking is not recomputable after the fact (`last_accessed` at that
step is gone); and the quoted lines are cut to conversations that had already
happened at that step, or an early reading gets rated on words the agent had not
said yet.

---

## Where this started

§9 had ruled out the prompt as the binding constraint and left a fork: feed the
probe real speech, or stop claiming a 100-point scale.

The first framing of the problem was mine and it was wrong. I had read Maya
Okonkwo's 85 as false precision and called ~45 "the correct reading of her
evidence" — i.e. a prompt/calibration problem. The reframe that turned out to be
right came from the question *"while plotting the graph we don't accidentally
want to retrieve agent's chat which in reality the agent may have forgotten"*:
the issue is **which evidence reaches the model**, not how the model reads it.
`seq_chat` is absent from the retrieval pool, so no agent had ever been rated on
anything it said out loud. See "Two things I got wrong" below.

---

## The chain, in order

### 1. Should spoken lines simply join the retrieval pool?

**Rejected, on two independent grounds.**

`new_retrieve`'s candidate pool is `seq_event + seq_thought` (`retrieve.py:232`),
under Stanford's own note that the raw conversation could be retrieved too, "but
for now". Adding `seq_chat` there is the one-line version of this whole feature.

- *Correctness:* that pool is read by planning, conversing and reflecting. It
  would be a change to the simulation, not to the observer. The probe already
  goes out of its way not to perturb what it measures (`touch=False`, and the
  relevance floor applied outside retrieval), so this would undo the invariant
  deliberately.
- *It would not have worked anyway:* spoken lines sit at a median cosine of
  **0.24** to the stance question against **0.51** for pool statements. Only 61
  of 431 utterances (14%) beat the weakest statement already being shown, and
  for Aisha it was **0 of 97**. In a shared ranking the lines lose essentially
  every time.

That second number is why the slots are **reserved** rather than competed for.
The reservation is not a convenience; without it the feature is inert.

→ to challenge: the 0.24/0.51 gap and the 61/431 count.

### 2. Reserved slots: quota or ceiling?

**Ceiling.** Rachel spoke 7 lines all day and fills 7; an agent that has said
nothing yet gets exactly the prompt it got before. A quota would have to pad
with lines that are not about the datacenter, which is the failure the relevance
floor exists to prevent. `RESERVED_N = 10` of `EVIDENCE_N = 30`, so 20 slots
remain for retrieved memories.

### 3. Should the utterance ranker include recency?

**No decayed weight. Yes to a bounded window, eventually.** This distinction is
the one to hold on to, because "we lose recency" is the obvious objection and
the answer is not simply "recency is bad".

A *decayed weight* — `extract_recency`'s `last_accessed` decay — is wrong for an
observer: `last_accessed` is a record of what the agent's own cognition happened
to touch, so a probe weighted by it reads the agent's recent attention rather
than its position, and it drifts for reasons that have nothing to do with the
datacenter. Worse, the quantity the graph is *for* is a trajectory, and a
decayed weight silently changes the instrument between two points on it.

A *bounded window* — "only consider the last N days of speech" — is principled
for the opposite reason: at day 300 you do not need day 40's evidence in the
prompt, because you already have day 40's reading. The graph is the trajectory.
Nothing bounded is built yet (see "Not built").

What *is* built is instrumentation: `quoted_span` records how many spoken lines
went in and the first/last timestamp they came from, on every row. It is a
measurement, not a gate. The failure it is there to catch — evidence drawn from
one early window while the simulation runs on — already shows in embryo: cosine
ranking alone does **not** cluster on a single game day (the top 10 spans the
full waking range), but Aisha had only 2 of 10 and Denise 1 of 10 from the later
half of the day.

→ to challenge: the `quoted` field on rows in `experiment/opinions.jsonl`.

### 4. Why keep cosine as the ranker at all?

Because of what it is and is not good at, measured separately:

| cosine top-10 vs baseline | hit rate |
|---|---|
| picking lines that are *about* the datacenter | **78%** (base 29%, recency 34%, random 26%) |
| picking lines that state a *position* | 35% (base 33%) — chance |

So cosine is a strong topicality filter and a worthless position detector. It
stays, for the first job only. The reason that is good enough is a base-rate
fact, not a ranking fact: position-bearing lines are **0.6%** of pool events and
**3.2%** of pool thoughts, against **33%** of the agent's own utterances. When
the source is 50× richer, selection quality inside it barely matters — which is
also, in advance, why step 8 below could not pay off.

### 5. How many slots? (the sweep)

24 readings, same recorded evidence, `RESERVED_N` swept. Full table in §11.5.
The decisive column is "above 50": **R=0 produces 0 readings above 50; every
R>0 produces 3.** Spoken evidence is what restores the instrument's ability to
register support at all. `R=10` also gives the most distinct values (9).

### 6. A per-statement relevance floor

`RELEVANCE_FLOOR` had been applied only to the single best statement, as a gate
on whether to rate at all. Measuring every statement individually: of 240, 35%
were below 0.45 and 14% below 0.35 — Luis carried 27 of 30 below the floor, and
Rachel 21 of 30, one at 0.108. So the floor now filters the list as well as
gating the reading. Luis's prompt drops to 9 statements, Rachel's to 10.

The gate condition changed from `shown is None or shown < RELEVANCE_FLOOR` to
just `shown is None`. **These are exactly equivalent:** at least one statement
survives the pre-filter precisely when the old max-based test would have passed.
If that filter is ever loosened, the gate has to come back.

→ note the asymmetry this creates: the floor cannot be applied to utterances at
all (median 0.24), so a reading can still be withheld for lack of pool relevance
while rich spoken evidence is sitting right there. It did not happen on this run.
No floor for utterances has been measured.

### 7. v1 → v2 of the stance prompt

v1 states its "above 50" bar four times, and that ceiling held even against
evidence that cleared it: 0 of 24 readings above 50, Maya at 45. v2 removes all
four ceilings and adds the attribution rule — a summary says what a conversation
covered, not what this person made of it. Result at R=10: 9 distinct, 3 above
50, Maya 85, and rationales move from *"Aisha is focused on the missing water
draw figure"* to *"I have serious concerns about the water usage"*.

Both templates are still on disk, so `--template` reproduces this directly.

### 8. Does a model extraction pass beat raw cosine? — **null, removed**

The last step of the plan was a model pass over the selected utterances ("quote
the lines where this person says what they want"), on the theory that better
position-detection would buy resolution. Built, measured on 16 readings, and
removed:

- position-bearing reserved lines: **56 raw against 56 extracted**
- most scores identical; Maya *fell* 85 → 70–75, because her advocacy is phrased
  collaboratively ("we could highlight how the datacenter could support job
  growth") and the extractor weakened it
- it found only 1–8 positions out of 30 lines, so the fallback refilled the slots
  with the same raw lines it was meant to improve on

Removed rather than shipped at one API call per agent per probe. 69 lines of
`run_gpt_prompt_datacenter_positions` and `datacenter_positions_v1.txt` deleted.
The prompt is preserved under "Dead ends" below so the null is re-testable.

### 9. The CI guard was vacuous

All five CI scripts reported 0 problems *after* the live template moved to v2 —
which should have been impossible, since `check_opinion_probe.py` asserted v1's
literal phrase. It had `datacenter_stance_v1.txt` hardcoded, so every check in
that block had been passing against a file the probe no longer opened. **A guard
pointed at a dead file is worse than no guard, because it reports that it
checked.** It now regexes the path out of
`inspect.getsource(run_gpt_prompt_datacenter_stance)`;
`sweep_reserved_slots.live_template()` does the same thing for the same reason.

Every new guard was then negative-tested — broken on purpose to confirm it
fires — rather than trusted because it passed. One of those negative tests (a
`sed` for the `said:` marker) silently failed to match due to escaping and made
a working guard look dead; re-tested with a Python string replace.

---

## Two things I got wrong

**Maya.** §9 concluded her 85 was false precision and ~45 was correct. With her
own words in evidence she reads 85 again, on *"I am actively pushing for the
datacenter because it is crucial for my funding round"* — which is what she
actually said. The mechanism I had identified (the old prompt converting
busyness into support) was real; it just happened to point the right way for her
and the wrong way for Elena Chen, who goes 85 → 40 and whose utterances confirm
an analyst with no position. Retraction is recorded in §11.5 too.

**Recency.** I first argued against recency on the grounds that the day-1 and
day-5 lines have to share a prompt. At year scale that under-stated the case in
one direction and over-stated it in another; see §3 above for the version that
survives — decayed weight bad, bounded window fine.

---

## Deliberately not built

| Not built | Why, and when to revisit |
|---|---|
| `seq_chat` in `new_retrieve`'s pool | Changes agent cognition, and loses the ranking anyway (§1). Only revisit if the goal becomes changing behaviour, not measuring it. |
| Recency in the utterance ranker | §3. A bounded window is the right shape; a decay is not. |
| Bounded candidate window, then a position ledger | The scaling path. Not needed at one game day; the forcing function is size, see below. |
| The extraction pass | §8, measured null. |
| A relevance floor for utterances | §6. No measurement exists; the case has not arisen. |

### The scaling ceiling is the memory architecture, not the probe

At 8 agents, one game day produces ~66 MB of embeddings — **~24 GB at a year**,
with ~28,424 of the agent's own turns per agent. Long before the probe's ranking
quality matters, Stanford's append-only memory with one embedding per node is
what breaks. The bounded window is the first fix; a running position ledger
(written once when a conversation ends, read cheaply forever after) is the
second. Neither is built.

---

## The finding that reframes the original request

The request that opened this round was for **more resolution**. The answer is
that retrieval is not where it comes from: across two prompts and four values of
`RESERVED_N` — eight configurations — **100% of scores were multiples of 5**.
Evidence density does not limit resolution; the model's round-number bias on a
1–100 scale does. The lever is the output format or the scale itself. Until that
changes, the honest description of the instrument is ~20 levels, not 100.

---

## Dead ends preserved

The extraction prompt, deleted from the repo in §8, kept here so the null result
can be re-tested without rewriting it:

> Pull out only the places where `<name>` says what they themselves want to
> happen to the datacenter. [...] If the line would still be true of someone who
> had no view either way, it is not a position. Do not resolve the
> contradictions.

Rebuilding it means re-adding `run_gpt_prompt_datacenter_positions` and filling
the reserved block from its output, with a fallback to the raw cosine lines when
it returns fewer than `RESERVED_N` — the fallback is what made the measured
result a tie rather than a loss.

---

## If a reading looks wrong, start here

| Symptom | Suspect | Re-run |
|---|---|---|
| Flat line across a multi-day run | Evidence anchored to the whisper seeds | `analyze_stance_evidence.py <sim>` — check seed share and evidence age |
| No reading ever goes above 50 | The prompt's ceilings are back, or `RESERVED_N` is 0 | `sweep_reserved_slots.py <sim> 0,10` |
| Scores all land on multiples of 5 | Expected. Output format, not retrieval | — (see above) |
| A reading is withheld though the agent talks about the datacenter constantly | The floor is measured on pool statements only (§6) | `relevance` and `quoted` on the row |
| Evidence stops advancing while the sim runs on | The §3 failure mode arriving | `quoted` span on recent rows |
| A score jumps with no conversation behind it | Attribution — a summary read as a position | `replay_stance_prompt.py <sim>`, and read the rationale |
| CI passes but a prompt change clearly broke something | A guard pointed at a dead file (§9) | Break the guard on purpose and confirm it fires |
