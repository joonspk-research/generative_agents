# Belief change: the private cast and probe validity

Why each change was made, what it replaced, and the evidence it is right.

The stance graph itself — the probe, the line, the event markers — is recorded
in [stance-graph-engineering-log.md](stance-graph-engineering-log.md). This log
covers the work after it: giving the 8 residents genuinely different starting
positions so their conversations have something to move, and then establishing
whether the graph is measuring those positions or just reading the seed text
back out.

Measurements below come from two existing runs, both `gpt-4o-mini`:

| run | span | readings | conversations |
|---|---|---|---|
| `stg-base_the_ville_datacenter_n8-2` | one game day, 8640 steps | 192 | 16 |
| `stg-base_the_ville_datacenter_n8-3` | ~11 game hours, 4000 steps | 88 | 3 |

---

## 0. What was built, and the order it had to happen in

The goal: 8 residents who disagree about the datacenter for *different reasons*,
so that watching them talk shows which kinds of argument move which kinds of
person — and a line graph that can be trusted to show that movement rather than
manufacture it.

1. **Persona fields** (§1) — durable traits that survive the day rollover.
2. **The private cast and its whisper seeding** (§2).
3. **Then, and only then, the measurement** (§3–§5). Steps 1 and 2 put more
   persona text in front of the probe, which made a pre-existing measurement
   flaw worse. Fixing the instrument after enriching the subject was the wrong
   order to discover things in, but the right order to fix them in: the flaw
   was invisible until the richer personas made it obvious.
4. **A tool to check the instrument against real data** (§6), which retracted
   one of the conclusions reached in §3.

---

## 1. Three new `Scratch` fields

`values`, `stake`, `persuadability` — added to `Scratch.__init__`, `load()`,
`save()` and `get_str_iss()`.

**Why fields and not prose in `currently`.** `revise_identity()`
(`plan.py:413`, called from `plan.py:490`) rewrites both `currently` and
`daily_plan_req` from the agent's reflections at **every game-day rollover**.
Anything stance-relevant written there is gone by the second morning. Since the
runs are multi-day, a durable trait had to be a real field. `innate` and
`learned` are never rewritten, but they are the donor personas' biographies and
were the wrong place for this.

**Why all four call sites.** `Scratch.save()` builds a **fresh dict** and
writes only the keys it names. A new attribute that is not added there is
silently dropped at the first autosave (step 360 by default) — the seed would
have loaded correctly and then lost the fields an hour into the run. `load()`
reads with `.get(field, "")` so the 68 pre-existing scratch files still load.

**What the fields are allowed to say.** `get_str_iss()` feeds ~12 prompt sites
*including the stance probe*. A field that states a position would be read
straight back out as a measurement, flattening the very graph the cast exists
to produce. So all three describe **how a person reasons**, never what they
conclude — `persuadability` says what someone credits and what they dismiss and
deliberately says nothing about which side they are on. Verified with a regex
assertion over all 8 personas; it caught two wordings ("receipts against
bills", "until a study supports one") that were reworded.

Emission is conditional: each field is omitted from the ISS when empty, so the
public cast's prompts are byte-identical to what they were before.

## 2. The private cast and the whisper CSV

`scripts/build_datacenter_n8_base.py` gained `PRIVATE_CAST` and a `--private`
flag; `main()` took `out` and `cast` parameters. The public
`base_the_ville_datacenter_n8` rebuilds unchanged.

Names, genders and donor personas are unchanged — `rename_homes` /
`HOME_RENAMES` keys off the donors, so changing them would break the
last-name home filter.

Each resident is movable by a **different mechanism**, which is the point:

| resident | what moves them | first measured reading |
|---|---|---|
| Maya Okonkwo | high anchor; little moves her | 80 |
| Denise Brooks | a concrete number (her $430/mo shop power bill) | 50 |
| Luis Hernandez | a signature — Local 332, the Fairview 2019 betrayal | 50 |
| Elena Chen | credible messenger who will not estimate out loud | 50 |
| Rachel Nguyen | whoever spoke to her last | 50 |
| Tom Whitaker | buyable; house paid off, 2/3 mile from the site | 23 |
| Aisha Rahman | one fact (the water draw) | 23 |
| Marcus Williams | procedure, not facts | abstained |

An earlier version of this table carried an "approx. start" column (Maya 88,
Luis 62, Marcus 12, and so on). Those were design intentions, and the seeds do
not encode them that tightly — deliberately, since **no agent is told their
position**. Measured against what the whispers actually say, the openings in
the column above are mostly right: Denise's $430 bill against a supplier's
remark about two years of construction lunches is a genuine 50; Marcus's
whispers object to the *process* and never to the facility, so an abstention is
the correct reading of them, not a failure. Luis is the one that reads low
against intent — forty-one members asking him about work leans further toward
the jobs than 50 — and is the seed worth revisiting.

`agent_history_init_datacenter_n8_private.csv` gives each agent 6–7 segments:
two **identical** public facts for all 8 (so they share a common world), then
private facts, two valenced named relationships, and their own stake. **No
agent is told their position** — the position has to be inferable from the
facts, or the probe is reading the seeding rather than the agent.

## 3. The probe was able to rate an agent from its description

`new_retrieve` (`retrieve.py:202`) normalizes relevance **within each call**
(`retrieve.py:244`, `normalize_dict_floats(relevance_out, 0, 1)`). The
consequence: the top-ranked node always scores 1.0 whether its true cosine was
0.8 or 0.1, there is no absolute relevance floor anywhere in the ranking, and
the rescaled score cannot supply one. The probe asks for `EVIDENCE_N = 30` and
gets 30, always. Nothing is ever evicted from the pool, which is every event
and thought the agent has ever had.

The old prompt then *asserted* that those memories "bear on the datacenter" and
required a number from 1 to 100. When the memories were in fact silent, the
only datacenter-adjacent text left in the prompt was the ISS — so the model
produced a confident reading of the persona text. That reading is **stable**,
because the persona text does not change, and on the graph a stable reading is
indistinguishable from a settled belief. "No data" and "no movement" drew the
same line.

**Fix: a first-class abstention**, not a relevance threshold.

- `STANCE_ABSTAIN = "none"`, a `parse_stance` branch returning
  `(None, rationale)`, and `is_stance_abstention()` so an abstention bypasses
  the 3-retry loop instead of being retried into the fail-safe.
- The prompt no longer claims relevance: *"They are the nearest ones in
  memory, which does not mean they bear on the datacenter at all."*
- A guard against over-abstaining: someone who has heard about it and has no
  settled view is a 50, not a `none`.
- `dashboard.html:915` already lifts the pen on a null score, so an abstention
  renders as a real gap.

**Why not a floor in `new_retrieve`.** The raw cosine only exists before line
244, inside the function every agent uses to perceive, plan and reflect. A
floor there would change the simulation being measured. Keeping the change in
the observer is the same principle as the probe's existing `touch=False`.

## 4. The probe now sees a name and an age, and nothing else

`stance_iss()` (`run_gpt_prompt.py`) replaced `get_str_iss()` in the stance
prompt.

The cold-start case in §3 turned out to be narrow — relevance plus importance
is two thirds of the ranking score, and the whisper seeds are both relevant and
poignant, so the probe usually does have real datacenter memories in hand. That
is not the reason this change was made.

The reason is `revise_identity` again. `currently` and `daily_plan_req` are
rewritten nightly from the agent's own reflections, and they sat in the probe's
prompt **every game hour**. So they were:

- a **second signal in every reading**, not a fallback that fires only when
  memories are silent;
- **drifting**, smoothly and directionally, in whatever direction the agent had
  been reflecting — the exact shape of the result the graph exists to detect;
- **double-counting**, since those reflections are already in the retrieval
  pool.

`innate` and `learned` went too: a position is inferable from them without
their ever stating one ("farmer, house paid off, two thirds of a mile from the
site"). Name and age stay because the retrieved memories name people.

Nothing is lost by this, because §2's whisper CSV already puts each agent's
stake into their memory stream as dated facts — which is where the probe should
be reading it from.

A CI rule in `check_opinion_probe.py` builds a stub scratch in which every
dropped field holds a tell-tale `<fieldname>` value, and fails by name if any
reappears. It also asserts `get_str_iss` is not called and that name and age
*are* still present. The negative control was verified to fire.

## 5. Relevance is now recorded, not guessed at

`measure_relevance()` in `opinion_probe.py` calls `extract_relevance`
(`retrieve.py:178`), which returns the **raw** cosines from before line 244's
rescaling, and writes two numbers onto every `opinions.jsonl` row:

```json
"relevance": {"shown": 0.41, "best": 0.41}
```

- `shown` — the closest memory the model was actually given. The floor below
  which a reading is worthless has to be read off this; it is a property of the
  embedding model and guessing it would either abstain constantly or never.
- `best` — the closest in the whole stream. **`best - shown` measures
  crowding-out**: a relevant memory that existed and lost its top-30 slot to
  recency and importance.

Costs one embedding of a constant string per probe and duplicates a cosine pass
`new_retrieve` already did internally. That duplication is the price of leaving
`new_retrieve` untouched, and it is worth paying. The `float()` cast is
load-bearing: `experiment_logger._append_jsonl` calls `json.dumps` with no
`default=` fallback.

## 6. What the existing runs actually showed — and one retraction

`scripts/analyze_stance_evidence.py` resolves each reading's `evidence` node
ids against the saved per-persona `nodes.json`. Seed share is **exact**: whisper
thoughts are the nodes sharing the earliest timestamp in memory, written before
step 1. (The `dc/30` column is keyword-matched and undercounts badly — in `-3`
seed share finds ~17 of 30 nodes are whispers where keywords find 3, because
most whisper segments never contain the literal word "datacenter". Read `seed%`,
not `dc/30`.)

**Seed dominance dilutes with run length**, which supports "longer runs":

| run | span | seed share |
|---|---|---|
| `-3` | 11 game hours | 57% |
| `-2` | one full game day | 29% |

**Retracted: "conversations cannot move this graph."** The first reading of this
data found conversation-derived evidence at 2–3% of all citations, with four of
eight agents never citing any, and concluded the channel was broken. That was
wrong. Those four agents had **zero conversations** in `-3`; every agent who
spoke had it cited, 8 for 8. The 2–3% is a base rate — 16 conversations against
thousands of perception events — not a bottleneck. The error was inferring
breakage from zero citations without checking whether there was anything to
cite.

The script now loads `conversations.jsonl` and prints a `convos` column with a
`channel` verdict per agent (`ok` / `no convos` / `DROPPED`), so the same
misreading cannot be made from its output. `DROPPED` — an agent who held
conversations that never reached a rating — is the only cell in the table that
indicates a real fault.

**Neither existing run can answer whether conversations move the line.** `-3`
is too short: 3 conversations, half the cast never spoke, and flat lines there
are the *correct* reading. `-2` is confounded: a full day, 16 conversations, all
8 agents speaking, healthy citations — and 7 of 8 scores flat, but every score
in it is one of 1, 3, 5, 7, 10. That is the old 10-point enumerated-anchor scale
and its documented snapping bug; the run physically could not show a small
shift. The first run that can answer the question is the first fresh one after
these changes — that is §8.

(`-2` and `-3` throughout this section are `stg-base_the_ville_datacenter_n8-2`
and `-3`, on the **public** seed. §8's run is on the private one and is a
different simulation despite the similar name.)

## 7. Deliberately not changed

- **`gpt_param["max_tokens"]`.** `ChatGPT_safe_generate_response` forwards only
  `temperature`; `ChatGPT_request` passes nothing else. The field is inert and
  the real ceiling is `chat_completion`'s default of 1024, so rationales were
  never being clipped at 120. An earlier claim that they were is withdrawn; the
  value stays at 120 with a comment saying it does nothing.
- **`recency_decay = 0.995`.** Raw decay is gentle — 0.887 over a day, 0.431
  over a week. But `normalize_dict_floats(recency_out, 0, 1)` rescales whatever
  range exists to the full [0,1], so recency acts as a **rank ordering of
  `last_accessed`**, not as a decay curve. Raising the constant is a monotone
  transform: same ranks, near-identical normalized scores. It would look like a
  fix and do nothing. The real lever, if one is needed, is `recency_w`.
- **Expanding chat-linked events into their utterances.** `perceive.py:152-177`
  gives a chat event the chat node's id as its `filling`, so the transcript is
  one dereference from the probe, which formats only `node.embedding_key`. This
  was briefly recommended on the strength of the 2% figure and is withdrawn
  along with it — see §6. Revisit only if `channel` reports `DROPPED`.
- **A relevance floor inside `new_retrieve`.** See §3.
- **`act_start_time` being `None` in bootstrap scratch files**, which makes
  `Scratch.save()` raise at `scratch.py:307`. Pre-existing, unrelated to this
  work, worked around in tests only.

## 8. The first clean run, and the six fixes it paid for

`stg-base_the_ville_datacenter_n8_private-2`, one full game day, 8640 steps,
192 readings, 31 conversations, `gpt-4o-mini`. This is the run §6 was waiting
for, and it settles most of what was open.

**The simulation is sound.** Conversations are in character and cluster
correctly in daylight (all 31 between game hours 8 and 20). Elena volunteers
"a 180 megawatt load is significant — about a third of what the Ville's
substation currently carries" and then refuses to go further; Denise cites her
power bill as a reason she cannot raise prices; Maya lobbies for a letter to
the council. Reflections match too — Marcus's highest-poignancy insight of the
day is *"Transparency and integrity are central to Marcus Williams's
decision-making approach"* (p10). Node counts scale with sociability (Maya 11
conversations / 1104 nodes; Rachel 1 / 313). All 53 whispers landed, 7–8 seeds
each.

**Resolved: no crowding-out.** `best - shown` is **0.0000 for five of eight
agents** and never above 0.15. The top `EVIDENCE_N` essentially always holds the
single most relevant memory the agent owns, so the planned 30 → 60 bump and the
probe-only `weights=` override are both unnecessary and are dropped.

**Resolved: the abstention floor is 0.45.** The probe abstained at a mean
`relevance.shown` of **0.389** and scored at **0.588** — two populations either
side of the floor, not a continuum.

**Seed share fell again**, 57% → 29% → **31%**, confirming dilution with run
length.

What the run also showed is that the probe, not the town, was the problem. Six
defects, each measured, each now fixed:

| # | defect | evidence | fix |
|---|---|---|---|
| 1 | engagement read as support | Elena ends at **85** on *"heavily involved in the planning and analysis… indicating strong support"*; she is the engineer paid to analyse it. Aisha reads 75 while hunting the missing water figure to argue against it | two new prompt paragraphs: activity is not a position, and an unanswered objection counts against |
| 2 | the prompt supplied the answer | **55 of 184 readings were exactly 23** — the number `example_output` carried — while all six values from 20 to 26 held **7** between them | example output moved to 71, on the far side of the scale from this cast so recurrence is visible; prompt tells the model not to reuse a value it was shown |
| 3 | content-free repetition | one conversation arrives as a dozen near-identical perception events; they filled a mean 19% and a maximum **80%** of a prompt. Tom's hr15 prompt: 30 statements, **15 distinct**, 22 of them "X is conversing about…" | `collapse()` folds the conversation family onto one entry; `RETRIEVE_N = 3 × EVIDENCE_N` refills the freed slots with distinct statements |
| 4 | rating sleeping agents | **64 of 192 readings (33%)** were of agents in bed; 5 of 41 consecutive asleep-to-asleep pairs moved ≥10 points, Rachel Nguyen alone oscillating 50 ↔ 70 three times in her sleep | `is_asleep()` withholds before retrieval, so it costs no API call |
| 5 | rating on irrelevant memory | Marcus at `shown=0.333` returned `none` six times and **70** three times on the same evidence | `RELEVANCE_FLOOR = 0.45`, applied to `shown` before the model is asked |
| 6 | parse failures stored as memories | **39** `"this is blank"` nodes in one day (Maya 15), **8** of them cited as stance evidence | `run_reflect` skips the `BLANK_INSIGHTS` sentinel |

Replayed against the saved run by `scripts/replay_stance_prompt.py`, the two
gates withhold **68 of 192 readings** — 35% of the LLM calls are no longer made
— and 62 of those were points the old code plotted. They come off the chart
where it was least informative: **23 of the 33 fifties**, 17 of the 55
twenty-threes, and 5 of the 10 seventies. `collapse()` frees a mean of 3.7 and a
maximum of 14 slots per prompt.

(An earlier draft of this section reported 38% asleep and 75 withheld. Those
came from an ad-hoc count that resolved each reading's sleep state against the
exact movement snapshot for its step. `movement/8640.json` does not exist — the
last probe ran and then the run saved — so the midnight readings, seven of eight
of them asleep, were being silently counted as awake, and other steps were
matched inconsistently. `sleeping_at()` now falls back to the nearest earlier
snapshot and every figure above comes from that one function, so they are
re-derivable rather than remembered.)

**The probe also has a measured noise floor.** Over 92 consecutive pairs whose
evidence was ≥85% identical, the median move is 0 and the mean 2.8 — stable.
But eight pairs moved ≥15 points, and those are nearly every sharp feature on
the chart:

| agent | hours | score | evidence identical |
|---|---|---|---|
| Elena Chen | 16→17 | 70 → 30 | **100%** |
| Luis Hernandez | 1→2 | 23 → 50 | **100%** |
| Denise Brooks | 23→24 | 1 → 23 | **100%** |
| Rachel Nguyen | 2→3, 3→4, 6→7, 7→8 | 50 ↔ 70 ×4 | **100%** |

Temperature is 0. Elena's 40-point crash came off a **30/30 identical** memory
set, where the only thing that changed in the prompt was the clock. None of the
six fixes removes this; what they remove is the fraction of the chart where it
has room to operate (fixes 4 and 5 delete a third of the readings, and 1 and 2
remove the attractors it was oscillating between). Treat hour-to-hour moves under
~15 points as noise until a repeat-probe measurement says otherwise.

`analyze_stance_evidence.py` now reports the mode's share with a threshold that
fires on this exact pattern, and splits withheld readings by reason, so fixes 2,
4 and 5 are checkable from its output on every future run. Seven negative
controls confirm each new CI rule fails when its fix is reverted.

## 9. The replay, and what it found instead

`scripts/replay_stance_prompt.py` re-reads a finished run's readings through the
current prompt. Each reading records its evidence node ids, associative memory
only appends, so the model's input is reconstructable from disk: feed the same
evidence through a changed prompt and the difference is the prompt, with the
simulation held fixed. A fresh run cannot separate the two.

124 of the 192 readings replayed (the gates withhold the rest). 122 scored under
both prompts. The result is **not** the one the fix was aiming for:

| | old prompt | new prompt |
|---|---|---|
| distinct values | 25 | **9** |
| multiples of 5 | 41% | **95%** |
| mode | 23, 31% | 30, **38%**, zero neighbours |
| readings above 50 | some | **0 of 122** |
| crossings through 50 | — | 35 down, **0 up** |

The 23 anchor is gone and a worse one replaced it. Every reading moved one way.
Maya Okonkwo, the one resident whose stake points at wanting it built, went from
85 to 30.

Two more prompts were written and tested on a 24-reading sample, three readings
per agent from late in the day:

- **v2** scoped the objection rule to objections *this person is pressing* and
  added the symmetric clause for enthusiasms. It fixed attribution visibly —
  rationales changed from "Aisha is focused on concerns about water usage" to
  "I have raised concerns about water usage" — and recovered Maya to 40–45.
  Granularity got worse: 5 distinct values, 100% multiples of five.
- **v3** removed every instruction that names 50 as a threshold, on the theory
  that the bin language was causing both the one-sidedness and the rounding, and
  moved the use-the-whole-scale paragraph to the end. **No effect**: 5 distinct
  values, 100% multiples of five, nothing above 50, mode 30.

Three substantially different wordings agreeing to within a few points is the
finding. It is not the prompt.

**The evidence contains no positions.** Across the eight last-of-day prompts,
240 statements, **5 of them (2%)** contain any verb of position — wants,
supports, opposes, argues, objects. 176 of 240 are reflection *thoughts*, and
reflection emits de-personalised abstractions. Maya's 28 statements at step 8280
include "Financial implications are a primary concern in the datacenter
proposal", "Collaboration among stakeholders is crucial for the success of the
datacenter proposal", and "Community concerns regarding the datacenter's impact
on local resources must be prioritized to gain stakeholder support". Nothing in
that prompt says what Maya thinks. The only Maya-specific line, repeated four
times, is that the site competition is "crucial for Maya's funding round".

So the old prompt's richness was false precision: it was converting *this person
is busy with the datacenter* into *85, in support*, and the apparent resolution
came from that invention. The new reading of Maya — around 45, no settled
position, stake noted — is the correct reading of her evidence. What the replay
actually measured is that **this instrument resolves about five levels, not a
hundred**, and the limit is set by the evidence rather than by the scale or the
wording.

The transcripts are better than the summaries but not by as much as hoped. Maya
to Aisha: *"Have you found any solid figures on the water draw yet?"* — real
voice, real specifics, still no stance, and much of the dialogue is scheduling
("Wednesday afternoon works for me").

Consequence for §7: **"expanding chat-linked events into their utterances" is no
longer deliberately-not-changed.** It was parked on the strength of the
retracted 2% citation figure; the 2% *position-bearing* figure is a different
measurement and it points the other way.

## 10. Still open

- **Done, in §9** — and it found that the prompt was not the binding
  constraint. The open item it leaves behind is whether to feed the probe real
  speech or to stop claiming a 100-point scale.
- **Quantify the noise floor properly**: probe the same unchanged memory set
  three times in a row and record the spread. The eight pairs above are
  circumstantial — evidence-identical but one hour apart — and cannot separate
  API nondeterminism at temperature 0 from genuine sensitivity to the clock
  token. If it is the clock, dropping `!<INPUT 5>!` to a date without an hour
  is the fix.
- **A ~13% insight parse-failure rate.** 39 blank sentinels across roughly 300
  insight batches. Fix 6 stops them polluting memory but each one still silently
  costs a whole focal point's reflections. Worth looking at
  `run_gpt_prompt_insight_and_guidance`'s output contract.
- **Luis's seed** reads 50 where the cast aims higher; see §2.
- **Reflection volume** is 7–21 episodes/agent/day against the paper's 2–3, and
  23% of insights have a >60% similar sibling written at the same timestamp.
  Not addressed here. It inflates poignancy for whatever an agent happens to be
  dwelling on, which is the likeliest cause of Rachel's hour-20 drop: four
  near-duplicate "utility rates hurt after-school programs" thoughts written at
  19:41, eight hours after her only conversation.
- `analyze_stance_evidence.py` does not filter rows inherited from a parent run,
  which is why `-3` and `-4` report identically. Pass a single sim when it
  matters.

## 11. Giving the probe the agent's own words

§9 ended by ruling out the prompt as the binding constraint and leaving one
question: feed the probe real speech, or stop claiming a 100-point scale. This
section does the first.

This section records what was built and the numbers behind it. The alternatives
that were considered and rejected, which measurement killed each, and what to
re-run to challenge any of it are in
[own-words-evidence-decision-trail.md](own-words-evidence-decision-trail.md).

### 11.1 Why spoken lines cannot simply join the pool

`seq_chat` is absent from `new_retrieve`'s candidate pool (`retrieve.py:232`,
under Stanford's own note that the raw conversation could be retrieved too,
"but for now"). Adding it there would change what every agent retrieves while
planning, conversing and reflecting — a change to the simulation, not to the
observer — so the probe reads the chat nodes itself, the same way `touch=False`
and the relevance floor keep observer concerns out of agent cognition.

The obvious alternative, letting utterances compete in one ranked list, was
measured and **does not work**:

| | median cosine to the question | max | beats the weakest statement already in the prompt |
|---|---|---|---|
| own utterances (431) | **0.24** | 0.39–0.59 | 61 of 431 (14%) |
| statements in the 8 last-of-day prompts (240) | **0.51** | 0.68 | — |

Aisha Rahman has 97 utterances and **none** outscores even her weakest shown
statement. The cause is register, not informativeness: the pool's statements
are model-written summaries in the same abstract third-person shape as the
stance question, while an utterance is conversational and spends most of its
tokens on greeting and hedging. The text that actually contains a position
scores lowest *because* it was spoken. Hence reserved slots rather than earned
ones — `RESERVED_N = 10` of `EVIDENCE_N = 30`.

### 11.2 What cosine is and is not good for here

| ranker, top 10 per agent | on-topic | position-bearing |
|---|---|---|
| base rate across all 431 | 29% | 33% |
| random 10 | 26% | — |
| most recent 10 | 34% | — |
| **top 10 by cosine** | **78%** | 35% |

Cosine is **chance** at finding positions (35% against a 33% base rate) and
2.7× base at finding topicality. Topicality is the job being asked of it;
position density comes from the base rate, which is fifty times the pool's —
**33% of own utterances state a position, against 3.2% of pool thoughts and
0.6% of pool events**. When the base rate is that much higher, selection
quality barely matters and the ranker does not need to be clever.

### 11.3 Recency, and why it is deliberately not in the utterance ranker

Recency as a *decaying weight* tracks what an agent last thought about, so an
agent who argued a position and then got busy has its evidence fade and its
line drift toward 50 — reporting a drop in attention as a change of mind. That
is the same class of artifact as rating a sleeping agent. The trajectory work
is done model-side instead: lines go in oldest-first and dated, and the prompt
says the most recent ones are what this person thinks now.

Measured on one game day, cosine-only ranking does **not** cluster in time —
the top ten spanned 09:23–20:46 of Aisha's 09:23–20:46, and similar for the
rest. But two agents tilt early (2 of 10 and 1 of 10 in the later half), which
is the long-run failure mode in embryo: the top ten of a year's conversations
would come from whichever week the agent argued about this most. `quoted_span`
logs the window on every reading so a multi-day run shows that collapsing
instead of having to be guessed at. The scaling path, when it triggers, is a
bounded candidate window (last N days, N > the time a belief change takes)
and then a position ledger written at conversation time. Neither is built: at
one game day there is nothing to fix, and the Stanford memory architecture
hits a harder wall first — 66 MB of embeddings per game day for eight agents
is **24 GB** at a year, loaded whole per persona and rewritten whole on save.

### 11.4 Filtering after retrieval

Until now `RELEVANCE_FLOOR` was applied only to the *closest* statement in a
prompt, as a go/no-go for the whole reading; every other statement went in
regardless of its own cosine. Across the 8 last-of-day prompts, 240
statements, **35% sat below the floor and 14% below 0.35**:

| agent | median | min | below 0.45 |
|---|---|---|---|
| Luis Hernandez | 0.351 | 0.298 | **27 of 30** |
| Rachel Nguyen | 0.341 | 0.108 | **21 of 30** |
| Denise Brooks | 0.441 | 0.343 | 17 of 30 |
| Elena Chen | 0.466 | 0.313 | 14 of 30 |
| Marcus Williams | 0.575 | 0.489 | 0 of 30 |

A reading could clear the gate on one 0.63 statement and then be rated on 29
lines of noise. The floor is now applied per statement, which can leave a
prompt short of `EVIDENCE_N` — the honest outcome, since there were not that
many relevant memories. Luis's prompt goes from 30 statements to 9 and
Rachel's to 10. The gate itself is unchanged: at least one statement survives
exactly when the old max-based test passed.

### 11.5 Result

24 readings (last 3 kept per agent) replayed with the same recorded evidence,
sweeping `RESERVED_N`. `R=0` is the baseline, so the sweep isolates the
evidence change from the prompt change.

| | distinct | mult of 5 | mode | above 50 | mean |
|---|---|---|---|---|---|
| as run (old prompt) | 9 | 50% | 23 ×7 | 6 | 33 |
| R=0 | 6 | 100% | 20 ×7 | **0** | 30 |
| R=5 | 7 | 100% | 20 ×6 | 3 | 34 |
| **R=10** | **9** | 100% | 30 ×4 | 3 | 34 |
| R=15 | 7 | 100% | 30 ×6 | 3 | 34 |

**`RESERVED_N = 10` ships**: most distinct values, and it leaves 20 slots to
the retrieved memories. Rachel, with 7 utterances all day, fills 7 — the
reservation is a ceiling, not a quota, and before anyone has spoken the prompt
is exactly what it was.

**The §9 retraction, retracted in part.** §9 concluded that Maya Okonkwo's 85
was false precision and that ~45 was "the correct reading of her evidence".
That was correct *for the pool* and wrong about Maya. With her own words in
front of the model she reads **85** again, on the rationale *"I am actively
pushing for the datacenter because it is crucial for my funding round and I
believe it will benefit local businesses"* — which is what she actually said.
The old prompt reached the right number by the wrong route, converting
busyness into support; that mechanism was real, and it happened to point the
right way for her and the wrong way for Elena Chen, who goes 85 → 40 and whose
utterances confirm an analyst with no position. Readings above 50 go from 0 at
R=0 back to 3, so spoken evidence is what restores the instrument's ability to
see support at all.

### 11.6 v2 over v1, measured

| at R=10 | distinct | mult of 5 | above 50 | Maya |
|---|---|---|---|---|
| `datacenter_stance_v1.txt` | 6 | 100% | **0** | 45 |
| `datacenter_stance_v2.txt` | 9 | 100% | 3 | **85** |

v1 states the above-50 bar four times, and that ceiling holds even against
evidence that clears it. v2 also fixes attribution — rationales move from
*"Aisha is focused on the missing water draw figure"* to *"I have serious
concerns about the water usage"* — by telling the model that a summary records
what a conversation covered rather than what anyone made of it. `check_opinion_probe.py`
now reads the template path out of `run_gpt_prompt` instead of hardcoding it:
it had been asserting against `v1` and would have gone on passing after the
loader moved, which is worse than no guard because it reports that it checked.

### 11.7 The extraction pass: built, measured, removed

A model-side pass over the selected utterances ("quote the lines where this
person says what they want") was built and tested on 16 readings. It is a
**null result**: position-bearing reserved lines came out at **56 raw against
56 extracted**, most scores were identical, and Maya *fell* from 85 to 70–75
because her advocacy is phrased collaboratively ("we could highlight how the
datacenter could support job growth") and the extractor weakened it. It found
only 1–8 positions from 30 utterances, so the fallback refilled the slots with
the same raw lines. Removed rather than left in at a cost of one API call per
agent per probe.

The useful finding is what it rules out. **Evidence density is not what limits
resolution** — every configuration above, across two prompts and four values
of `RESERVED_N`, came back **100% multiples of 5**. The binding constraint is
the model's round-number bias on a 1-100 scale, which no amount of better
evidence touches. The lever is the output format or the scale itself, not the
retrieval.

### 11.8 Still open after this section

- **Resolution is ~20 levels, not 100**, and it is now clear that is a scale
  and output-format problem rather than an evidence problem. Either change what
  the model is asked to emit, or stop calling it a 100-point scale.
- **A reading can still be withheld while rich spoken evidence exists.** The
  gate is measured on pool statements only, because utterances sit at a median
  0.24 and `RELEVANCE_FLOOR` cannot be applied to them; no separate floor for
  them has been measured. On this run every kept reading had at least one
  statement above the floor, so the case did not arise.
- **A fresh run has not been done** since any of this. Everything in §11 is
  replay against `stg-base_the_ville_datacenter_n8_private-2`.
