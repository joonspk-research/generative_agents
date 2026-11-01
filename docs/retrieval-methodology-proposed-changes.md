# Stance evidence retrieval: how it works, and proposed changes

**Status: proposal. Nothing in here has been implemented.** Written to be read
by someone who has not been following the probe work, so the methodology can be
discussed before any code changes.

The stance graph rates each agent 1–100 on the datacenter every game hour. The
rating is a function of one prompt, and that prompt is a function of **which
memories and which spoken lines get selected**. This document is about the
selection, not the prompt. The prompt was audited and corrected already (see
[own-words-evidence-decision-trail.md](own-words-evidence-decision-trail.md));
the selection has only been patched, and the patches are now working against
each other.

Evidence base: the 2-day run `stg-base_the_ville_datacenter_n8_private-3` —
8 agents × 48 game hours = **384 probes** (176 scored, 177 asleep, 31 withheld
for low relevance). Every number below is from that run's
`experiment/opinions.jsonl` and the personas' saved `nodes.json`, unless marked
otherwise.

**What is being asked for:** sign-off on the five changes in §3 and the hygiene
items in §4, and answers to the open questions in §7. The changes are **not**
independent — §5 gives the required order.

Findings are labelled by how they were established. **Measured** = read off
saved run data. **Mechanical** = a property of the code, certain without running
it. **Latent** = predicted from the code, not yet observed.

---

## 1. How it works today

`opinion_probe.probe()` builds every prompt in six stages:

| Stage | Where | What happens |
|---|---|---|
| 1. Sleep gate | `opinion_probe.py:311` | `"sleep" in act_description` → withhold, before any API call |
| 2. Spoken lines | `rank_utterances`, `:316` | The agent's own turns, read straight off `seq_chat`, ranked by **raw cosine alone**, top `RESERVED_N = 10`. **No floor** — `ranked[:n]` |
| 3. Memories | `new_retrieve(..., 90, touch=False)`, `:318` | `seq_event + seq_thought` minus `"idle"`, ranked by the **composite** of recency × relevance × importance, each min-max normalized per call, `gw = [1,1,1]`, all three scratch weights 1 |
| 4. Dedup + floor | `collapse`, `:331` | Exact-canonical repeats dropped, then each surviving node must clear `RELEVANCE_FLOOR = 0.45` on **raw** cosine |
| 5. Truncate | `:333` | `retrieved[:EVIDENCE_N - len(quoted)]` → 20 memory slots when all 10 quote slots are used |
| 6. Relevance gate | `:337-348` | If **no memory survived**, withhold with reason `low_relevance`. Spoken lines are explicitly not allowed to lift this gate (`:339-343`) |

Surviving memories and spoken lines are then merged, sorted oldest-first, each
line dated, and handed to `run_gpt_prompt_datacenter_stance` at
`temperature = 0`.

Two properties of this design are load-bearing for everything below:

- **Relevance has two different roles.** In stage 3 it is one of three
  normalized components deciding *what gets nominated*. In stage 4 it is an
  absolute threshold deciding *what gets vetoed*. Nothing connects them.
- **The two streams are ranked separately and never compete.** That was
  deliberate and is correct — see §6.

## 2. Findings

### 2.1 The composite ranking nominates the wrong memories (measured)

`new_retrieve` min-max normalizes relevance **within each call**
(`retrieve.py:244`), so the most on-topic node scores 1.0 whether its true
cosine was 0.8 or 0.1, and the least on-topic scores 0.0 whether it was 0.5 or
0.01. The absolute scale — the only thing that says whether a memory is about
the datacenter at all — is destroyed before the ranking happens. Recency and
importance then get equal weight with it.

The consequence, on Luis Hernandez's 48 probes: across a memory stream of
**1,679 nodes**, his readings cited **5 distinct nodes**.

| Game hours | Memories in the prompt | Framing | Score |
|---|---|---|---|
| 9–36 | `node_1` (whisper seed, cos **0.565**) + `node_462` ("economic benefits… job creation… viewed positively") | benefit | 60–65 |
| 37–38 | none survive stage 4 → withheld, `best = 0.565` | — | **withheld** |
| 39–41 | asleep at 15:00, 16:00, 17:00 (genuine scheduled mid-day sleep) | — | withheld |
| 42–48 | `node_1266` ("presenting the main concerns gathered from neighbors", cos **0.489**) + `node_1418` (electricity rates) | concern | 30–40 |

That is the 65 → 30 cliff the audit started from. `node_1` at 0.565 was Luis's
single most relevant memory for the entire run. **It was never vetoed by the
floor — it was never nominated.** It fell out of the top 90 of the composite,
outranked by more recent and more poignant memories that had less to do with
the datacenter. The cliff is not a change of mind; it is the instrument
swapping one anchor sentence for another with the opposite valence.

### 2.2 Most agents' lines rest on a single anchor (measured)

The same effect, cast-wide. Distinct `shown` values — the closest memory the
model was actually given — per agent across the whole run:

| Agent | distinct `shown` | distinct nodes cited in 48 probes |
|---|---|---|
| Marcus Williams | `[0.486]` | **1** |
| Rachel Nguyen | `[0.563]` | **2** |
| Elena Chen | `[0.616]` | 5 |
| Luis Hernandez | `[0.489, 0.565]` | 5 |
| Aisha Rahman | `[0.47, 0.601]` | 10 |
| Tom Whitaker | `[0.594]` | 13 |
| Maya Okonkwo | 5 values | 17 |
| Denise Brooks | 4 values | 48 |

Five of eight agents have a **single-sentence anchor** for an entire two-day
line. A line anchored to one sentence cannot show belief change; it can only
show which sentence won the ranking that hour.

### 2.3 Supply is not the constraint; selection is (measured)

Across the 176 scored readings the prompt carried a **mean of 5.8 memory
statements** against 20 available slots. **89 of 176 (51%)** carried just 1–3.
Only **15 (9%)** filled all 20.

So the pipeline is not running out of room. It is running out of *nominations* —
stage 3 hands stage 4 a top-90 list in which almost nothing clears 0.45, and
the slots go unused while relevant memories sit in the pool unranked.

### 2.4 The quoted half freezes (measured)

`rank_utterances` ranks by relevance alone, with no recency term and no time
constraint, and takes the top 10 permanently. Once an agent's 10 best-scoring
lines are set, new conversations cannot displace them unless they outscore
them on cosine.

| Agent | probes with a byte-identical quote block | staleness at the end | conversations never quoted |
|---|---|---|---|
| Luis Hernandez | **18** | **25 game hours** | 2 of 9 |
| Aisha Rahman | 14 | 21 h | 1 of 13 |
| Rachel Nguyen | 8 | — | — |
| Denise Brooks | 8 | 4 h | 2 of 15 |
| Elena Chen | 11 | — | honest (no day-2 lines) |
| Marcus Williams | 6 | — | honest |
| Maya Okonkwo | 1 | current | — |
| Tom Whitaker | 2 | current | — |

Luis's quote block was frozen from game hour 19 to hour 48 — `first =
09:40:10`, `last = 18:10:10`, both on Feb 13 — while he went on holding
conversations through Feb 14. The failure is **content-dependent, not
volume-dependent**: Maya's 109 lines stay current and Luis's 67 go stale,
because what matters is whether a new line happens to outscore an old one.

### 2.5 Utterance timestamps are per-conversation, not per-turn (mechanical)

`own_utterances` stamps each line with the **parent chat node's** `created`
(`opinion_probe.py:183`, and its docstring says so). Luis's 67 deduplicated
lines carry **9 distinct timestamps**, 5–8 lines each. Two consequences:

- Within one conversation the lines appear in **cosine order, not dialogue
  order** — the sort at `:362` is stable, so ties keep their incoming order.
  A reply can precede the thing it replies to.
- At tied timestamps, pool summaries sort before verbatim lines.

### 2.6 The relevance gate reports a cause it did not test (measured)

The gate at `:338` tests `shown` — the best cosine among memories that
**survived selection**. The rationale it emits claims something else:
*"Nothing in X's memory is close enough to the datacenter to rate (relevance
N)."* Of the 31 `low_relevance` withholdings:

| | rows | `best` | rationale true? |
|---|---|---|---|
| Marcus Williams | 9 | 0.227 – 0.400 | **yes** — genuinely nothing relevant |
| Rachel Nguyen | 20 | 0.563 | **no** — a 0.563 memory was in the pool |
| Luis Hernandez | 2 | 0.565 | **no** |

**22 of 31 withheld readings** print a sentence the same log row disproves, and
it prints the disproving number inside the sentence. Mechanically, `best ≥ 0.45`
with `shown = None` can only mean the above-floor node placed below 90th on the
composite — §2.1's defect, surfacing as a gate error. `collapse()` cannot cause
it: it keeps the best-ranked member of each canonical group, and a dropped
duplicate has the same text and therefore the same cosine.

**15 of the 31** had spoken lines in hand and were suppressed anyway — Rachel at
`n = 7`, Marcus at `n = 10`. That is deliberate and documented at `:339-343`,
but it contradicts the prompt, which instructs the model to *"weigh this
person's own quoted words above any summary"* (`datacenter_stance_v2.txt:24`).

**`measure_relevance`'s docstring is now false.** It asserts: *"On the measured
run that gap was 0.0000 for five of eight agents and never above 0.15, so
nothing relevant is being crowded out at EVIDENCE_N = 30."* True of the
one-day run it was written from. On this run Rachel's gap is maximal —
`best = 0.563` against no `shown` at all.

### 2.7 What actually moves the line (measured)

Holding both halves of the prompt fixed and comparing consecutive readings
across all 168 scored transitions:

| | n | mean \|Δ\| | moves ≥ 15 | max \|Δ\| |
|---|---|---|---|---|
| prompt byte-identical | 104 (62%) | **1.0** | **0** | 10 |
| prompt changed | 64 (38%) | 6.1 | 10 | 40 |

At `temperature = 0` the model is effectively deterministic: identical input
moves the score by a mean of one point and never by fifteen. **About 80% of all
absolute movement in the graph is attributable to the prompt's contents
changing.** That is the good news — the instrument is not noisy — and the bad
news, because §2.1–2.4 say what changes the contents.

All five largest moves on *unchanged memory evidence* were **quote-block
refreshes**: Tom 0→8 quotes (50→20), Aisha 0→6 (50→30), Luis's span moving
(65→45, then 40→65), Maya 10→10 with a different 10 (40→60). The quoted half is
the single most consequential input and the least governed.

### 2.8 `last_accessed` is never persisted (mechanical)

`ConceptNode.__init__` takes 16 parameters; `last_accessed` is not one of them.
It is set at `associative_memory.py:33` as `self.last_accessed = self.created`,
written only at `retrieve.py:276` under `if touch:`, and **absent from the 13
fields `save()` writes**. There is no `def load` — loading is
`AssociativeMemory.__init__(f_saved)`, which re-dispatches through
`add_event` / `add_thought` / `add_chat` into that constructor. So there is no
code path by which a saved `last_accessed` could be restored, because none is
saved.

**This is upstream Stanford code** — `git log` on the file returns exactly one
commit, `6d7d7ad1 Initial commit`. And upstream it was nearly harmless: commit
`750d6eb7` shows `extract_recency` previously read

```python
recency_out[node.node_id] = recency_vals[count]
```

— decay by **position** in a list sorted by `last_accessed`. The field was only
ever a sort key, so resetting every node to `created` left the order roughly as
it was and positional decay barely noticed. Our own (correct, paper-faithful)
replacement

```python
hours_elapsed = ((persona.scratch.curr_time - node.last_accessed).total_seconds() / 3600)
recency_out[node.node_id] = persona.scratch.recency_decay ** hours_elapsed
```

is what made the absolute value load-bearing, and so promoted the omission from
latent to real. Not a Stanford blunder, and not a regression — a consequence of
fixing recency.

**Inert in this run** (forked at step 0, where `last_accessed == created`
anyway). It bites on any continued run: all 1,679 of Luis's nodes would reset to
"untouched since creation," silently degrading recency from *what the agent has
attended to* into *what is newest*. `retrieve.py:232` also sorts the candidate
pool by `last_accessed`, so that sort degenerates to creation order too.

Second, independent cost, already recorded in-repo: `sweep_reserved_slots.py`
notes that *"new_retrieve's composite ranking cannot be recomputed after the
fact (last_accessed at that step is not recoverable)"*. Both offline tools —
that one and `replay_stance_prompt.py` — carry a documented compromise because
of this field.

---

## 3. The changes

### 3.1 Step 1 — relevance nominates, not just vetoes

**What changes.** Select memory evidence by **raw cosine to the stance
question**, descending, keeping only nodes at or above `RELEVANCE_FLOOR`.
`pool_relevance()` already computes exactly these numbers for every node in the
pool on every probe (`opinion_probe.py:229`), so the cosines are already paid
for. `new_retrieve`'s composite stops governing which memories the *probe*
sees.

**Why.** Relevance currently does both jobs badly. Normalized, it cannot say
whether a memory is on-topic; as a post-hoc veto it can only reject what the
composite happened to offer. The probe asks one fixed question all run, so
"closest to that question" is the whole of what it needs — recency and
importance are the agent's planning priorities, not an observer's measurement
criterion. Ranking by them is how a highly relevant seed sentence loses to a
fresh thought about lunch.

**What it fixes.** §2.1 and §2.6 together. The highest-cosine node in the pool
becomes impossible to miss: it is the global maximum, so it ranks first
overall, first in any band, first in any timestamp group. Therefore
`best ≥ floor ⟹ shown = best`, and the contradictory state behind all 22
mislabelled withholdings (`best ≥ floor` **and** `shown = None`) becomes
**unreachable**. It also unfreezes Luis's anchor — `node_1` at 0.565 is his
pool maximum and would be selected at every probe.

**Important scope limit.** This changes the **probe only**. `new_retrieve` keeps
its composite for the agents' own planning and reflection, where recency and
importance are exactly right. Nothing about agent behaviour changes.

**Verify.** On a replay of this run, every reading's `shown` equals its `best`
whenever `best ≥ 0.45`. Luis cites `node_1` in all 48 probes.

### 3.2 Step 2 — time-stratified memory slots (8/7/5)

**What changes.** Divide the 20 memory slots into three age bands and fill each
by cosine within the band:

| Band | Age at probe time | Slots |
|---|---|---|
| recent | ≤ 12 game hours | 8 |
| mid | 12–36 h | 7 |
| old | > 36 h | 5 |

Plus a **per-timestamp cap** so one conversation's worth of near-identical
perception events cannot occupy a whole band. Unfilled slots in any band
**spill to the next-best candidate anywhere**, so no slot is wasted when a band
is empty.

**Why.** Step 1 alone has a known failure mode: pure cosine ranking has no time
term at all, so on a long run the top 20 collapse onto whichever period the
agent discussed the datacenter most intensely — and the line then reports a
position the agent has since moved off. Stratifying guarantees the prompt always
contains *something from now* and *something from before*, which is the minimum
for the model to answer the question the prompt actually asks: what does this
agent think **at the end** of these memories. The 8/7/5 taper weights the
present without erasing the past.

**Honest sizing.** On *this* run step 2 rarely binds — mean 5.8 statements used
of 20 slots (§2.3), so it changes only the 9% of readings that saturate.
**It is insurance for multi-day runs, not a fix for the numbers in §2.** Step 1
is what fixes this run. Step 2 is what stops step 1 creating a new problem at
week scale.

**Verify.** On a saturated reading, each band's occupancy matches its quota or
is empty-and-spilled; no timestamp exceeds the cap.

### 3.3 Step 3 — time-stratified utterance slots (4/6)

**What changes.** The same device on the 10 reserved quote slots, at
**conversation grain** (because that is the resolution the timestamps have —
§2.5): **4 slots** to the agent's most recent conversations, **6** ranked by
cosine across everything earlier. Within a conversation, emit lines in
**dialogue order**, not cosine order.

**Why.** This is the one change that fixes a defect which is **demonstrably
biting right now**, not a forward-looking guard. §2.4: Luis frozen for 18
probes and 25 game hours, two conversations never quoted at all; §2.7: quote
refreshes are the largest single cause of score movement. Reserving slots for
recent speech means a conversation the agent just had is guaranteed to reach
the prompt, which is precisely what the graph exists to detect. And §2.5's
dialogue-order fix is nearly free: it removes prompts in which a reply precedes
what it replies to.

**Verify.** No agent's quote block is byte-identical across a wake period in
which they held a conversation. Luis's `quoted.last` tracks his latest
conversation.

### 3.4 Step 5a — log the selection

**What changes.** Each row in `opinions.jsonl` additionally records:

- the **per-statement cosine** of every memory that went into the prompt;
- the **per-line cosine** of every quoted utterance;
- the **near-miss candidates** — the few highest-cosine nodes that were
  *rejected*, with the reason (below floor / band full / timestamp cap);
- the resolved band occupancy.

**Why.** Three concrete things in this document could not be settled from the
log and had to be inferred:

1. Whether Marcus's 10 quoted lines would clear any plausible floor (§6) —
   unanswerable, because no per-line cosine is stored anywhere.
2. Whether a given withholding was crowding-out or genuine scarcity — only
   resolvable via the `best`/`shown` gap, which is a two-number proxy for what
   should be a direct record.
3. The composite rank of Luis's `node_1` — unrecoverable, per §2.8.

It also makes replay **exact**. Both existing offline tools carry a documented
compromise because the ranking is not reconstructable; once selection is a
logged list of cosines (step 1) the compromise disappears, and
`replay_stance_prompt.py` / `sweep_reserved_slots.py` become faithful rather
than approximate.

**Cost.** Zero additional API calls — `pool_relevance()` already computes every
one of these numbers on every probe and discards all but two. The whole change
is "write down what you already calculated." Size: ~30 floats per row against
the ~4000 rows the dashboard already reads, and `translator/dashboard.py`
`_opinions()` already strips analysis fields before they reach the browser, so
the payload does not grow.

**Verify.** For any logged row, re-deriving the prompt from the logged cosines
reproduces the prompt byte-for-byte.

### 3.5 Step 5b — persist `last_accessed`

**What changes.** Three edits:

1. `ConceptNode.__init__` takes `last_accessed=None`, defaulting to `created`
   when absent.
2. `save()` writes it.
3. `add_event` / `add_thought` / `add_chat` pass it through when loading.

**Why.** §2.8. Backward compatible by construction: an existing `nodes.json`
has no such field, the default fires, and behaviour is identical to today.

**Scope note.** This is a **simulation-side** fix and is *not* part of the
retrieval redesign — it does not change what the probe selects. It is bundled
here because §2.8 was found while auditing the probe, and because leaving it
unfixed makes every future long run's recency quietly wrong and every offline
replay approximate. It can be taken or deferred independently of steps 1–3.

**Verify.** Save a run, reload it, and confirm each node's `last_accessed`
survives; confirm a `nodes.json` without the field still loads and yields
`last_accessed == created`. `check_retrieval.py` already asserts both sides of
`touch` and is the natural home for the round-trip rule.

### 3.6 Hygiene (what remains of the old "step 6")

The original sixth proposal was to fix the relevance gate by testing `best`
instead of `shown`. **Step 1 makes that unnecessary**: the two tests become
equivalent, so `if shown is None` is already correct once cosine nominates, and
the rationale that prints `best` becomes true for the first time. What is left
is labelling, not logic:

| Item | Change | Why |
|---|---|---|
| `low_relevance` | rename `no_relevant_memory` | Post-step-1 it can only mean one thing; the old name named a symptom |
| `asleep` | split `asleep_night` / `asleep_daytime` | **28 agent-daytime-hours** were scheduled mid-day sleep (Marcus 13 of them) — a planner defect, which should not hide inside the same label as 3 a.m. |
| sleep detection | sample the game hour, not the instant | **28 of 177** asleep withholdings had the agent active elsewhere in that same hour: the probe fires at the top of the hour, before the waking action is installed. Recovers 28 readings |
| `measure_relevance` docstring | rewrite | §2.6 — it currently asserts the opposite of what this run shows. Steps 1–2 make "nothing is crowded out" true again, but for a different reason than the one written there |
| `analyze_stance_evidence.py` | teach it about `quoted` | Its `channel` verdict is computed from `chat_event` + `planning` ids only, so it reports **DROPPED** for agents whose conversations reached the prompt through the quoted stream. False alarms today |

---

## 4. Expected effect on this run

Stated as a prediction so the implementation can be checked against it. Step 1
is the only change whose effect is exactly computable in advance (every
`low_relevance` row with `best ≥ 0.45` becomes a reading, by construction):

| Agent | scored today | after step 1 | why |
|---|---|---|---|
| Rachel Nguyen | 12 | **32** (+20) | `best = 0.563`, above floor on every withheld row |
| Luis Hernandez | 26 | **28** (+2) | `best = 0.565`; also removes the 65→30 cliff at hr 42 |
| Marcus Williams | 3 | 3 | `best = 0.227–0.400`, correctly withheld |
| all others | 143 | 143 | no `low_relevance` rows |
| **total** | **176** | **198** | |

Plus, from §3.6, **+28** readings recovered from the stale-sleep boundary, and
Marcus's 13 daytime-sleep hours reclassified rather than recovered.

Steps 2 and 3 change *which* statements fill the prompts, so their effect is not
computable in advance — but §2.7 bounds it: at `temperature = 0`, prompts that
do not change do not move, so any movement they produce is attributable to the
evidence and nothing else. `sweep_reserved_slots.py` can measure them offline
against this run before any new run is paid for.

## 5. Dependency order

**Steps 1 and 2 ship together.** Step 1 alone removes the time term from
selection entirely; on a long run that is a regression (§3.2).

**Step 3 is independent** and could ship first. It fixes a present, measured
defect and touches only `rank_utterances` / `own_utterances`.

**Step 5a should ship with or before 1–3**, because it is what makes their
effect measurable. Shipping the algorithm changes first means the first run
under the new scheme cannot be audited any better than this one could.

**Step 5b is independent** of all of the above.

**Hygiene (§3.6) ships after step 1**, since the relabelling only becomes
accurate once the gate and the selection agree.

Recommended order: **5a → 1 + 2 → 3 → §3.6 → 5b**.

## 6. What this does *not* change

Guard rails, so review can be scoped. Each of these was considered and
deliberately left alone:

- **Agent behaviour.** `new_retrieve`'s composite keeps governing planning and
  reflection. Only the probe's selection changes. `touch=False` stays.
- **The two-stream design.** Memories and spoken lines keep being ranked
  separately with reserved slots. They cannot share one ranking: utterances
  sit at a median cosine of **0.24** against the question where pool statements
  sit at **0.51**, and only 61 of 431 utterances outscored the weakest
  statement already in a prompt — for one agent, none of 97 did
  (`rank_utterances` docstring). In a shared ranking they lose every slot,
  every time.
- **No floor on utterance selection.** Applying 0.45 to a population whose
  median is 0.24 would delete most of the stream — the stream that exists
  because the pool has the positions stripped out of it (33% of spoken lines
  carry a verb of position against 0.6% of pool events and 3.2% of pool
  thoughts; Maya reads 40 on her summaries and 85 on her own words). And
  displacement is not a real cost: the memory half fills all 20 of its slots on
  only 9% of readings.
- **Utterances still cannot lift the relevance gate.** Under step 1 the memory
  gate alone fixes **22 of 22** false withholdings. The only rows an utterance
  clause could touch are Marcus's 5 (`best = 0.3998`, `quoted n = 10`), and his
  entire pool tops out at 0.40. Adding the clause fixes **zero** additional
  rows in this run, and would require inventing a threshold nobody has
  measured. See the open question in §7.
- **The prompt.** No wording change. `datacenter_stance_v2.txt` stays as is.
- **`seq_chat` stays out of `new_retrieve`'s pool.** Widening it would change
  what every agent retrieves while planning — a change to the simulation, not
  to the observer. The probe keeps reading chat nodes itself.
- **Chart-side evidence annotation** (the original "step 4" — marking evidence
  turnover on the graph) is **dropped from scope**. It is presentation, it
  changes no retrieval behaviour, and the turnover signal it would draw is rare
  enough to be a tooltip rather than a glyph: only 5 of 168 transitions fall
  below 0.5 evidence overlap and exactly one hits zero.

## 7. Open questions

1. **Band boundaries (§3.2).** 12 h / 36 h and 8/7/5 are a starting proposal,
   chosen so that on a 2-day run all three bands are reachable. Should the
   boundaries be absolute hours, or a fraction of elapsed run time so they
   scale to a 7-day run? `sweep_reserved_slots.py` can test alternatives
   offline against this run.
2. **The utterance floor.** Should a measured floor be added to the gate later?
   One measurement settles it: with 5a shipped, read the per-line cosines of
   Marcus's 10 lines from 12:08–14:04. Near 0.38 and the gate was right to
   withhold — no clause needed. Near 0.55 and we have a genuinely missed
   reading, with a number we measured rather than borrowed.
3. **Daytime sleep (§3.6).** Marcus slept 36 of 48 hours, 13 of them mid-day,
   leaving 3 scored readings. Is that a planner bug worth fixing, or a
   legitimate agent whose line should simply be sparse? It is out of this
   document's scope either way, but it caps what any retrieval change can do
   for him.
4. **Does the probe's question need to be fixed for all time?** Step 1 makes
   selection a pure function of cosine to `STANCE_QUESTION`. That is clean, and
   it means changing the question's wording changes every historical reading's
   comparability. Worth an explicit decision to freeze the string.

## 8. Checks and comments that will need updating

| File | Why |
|---|---|
| `scripts/ci/check_opinion_probe.py` | Its five rules describe the current selection path. The "evidence reaches the model oldest-first and dated" rule survives; rules about the composite do not |
| `scripts/ci/check_retrieval.py` | Unchanged by steps 1–3 (agent retrieval is untouched), but it is the right home for 5b's save/load round-trip rule |
| `opinion_probe.py` module docstring | Describes the two-stream design and the three withholding reasons. Both change |
| `measure_relevance` docstring | Asserts no crowding-out (§2.6) — currently false |
| `probe()` inline comment at `:321-330` | States *"The gate is unchanged by this, because at least one statement survives exactly when the old max-based test passed."* True today; step 1 is what makes the gate and the selection the same test, and the comment should say so |
| `scripts/analyze_stance_evidence.py` | §3.6 — false DROPPED verdicts |
| `scripts/replay_stance_prompt.py`, `scripts/sweep_reserved_slots.py` | Both document a compromise forced by §2.8; 5a + step 1 remove it |

---

## Related documents

- [belief-change-cast-and-probe-log.md](belief-change-cast-and-probe-log.md) —
  the full measurement record this draws on.
- [own-words-evidence-decision-trail.md](own-words-evidence-decision-trail.md) —
  why the spoken-lines stream exists at all.
- [stance-graph-engineering-log.md](stance-graph-engineering-log.md) /
  [stance-graph-change-map.md](stance-graph-change-map.md) — the previous round
  of probe work, which these changes build on.
- [interview-proposed-changes.md](interview-proposed-changes.md) — the
  qualitative instrument, which has the same `seq_chat` blind spot (§3.1 there)
  and would benefit from step 1 for the same reasons.
