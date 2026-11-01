# Stance evidence retrieval — implementation

What shipped against `docs/retrieval-methodology-proposed-changes.md`, which is
the approved artifact and is left byte-identical. Baseline `dd162fc9` on
`mhdgohel-datacenter-town`, which already carried the teammate's `rubric_v1`
scorer.

The two layers stay separate throughout. **Scoring** — the prompt, the seven
bands, the parser — is `rubric_v1` and is untouched here. **Selection** — which
statements enter that prompt — is what this change is. They meet at the
`statements` string `probe()` builds.

## What was wrong

The probe selected evidence with `new_retrieve`'s composite of recency ×
relevance × importance, equally weighted (`retrieve.py:252`), each component
min-max normalized inside each call (`retrieve.py:244`). Those are an agent's
planning priorities, not an observer's measurement criterion. Because relevance
was rescaled per call, it could not say whether a memory was on-topic at all;
the raw cosine was then applied as a post-hoc veto, so it could reject what the
composite offered but never nominate what the composite missed.

Measured over one game day — 384 readings, 8 agents, 176 scored:

- Luis Hernandez cited 5 of his 1,679 nodes.
- 5 of 8 agents rested on a single anchor memory for the whole run.
- 22 of 31 `low_relevance` withholdings had a pool memory **above** the 0.45
  floor and were mislabelled.
- 28 of 177 `asleep` withholdings had the agent active elsewhere in that same
  game hour.

## What shipped

### Relevance nominates; bands hold the past open

`probe()` no longer calls `new_retrieve`. It ranks the whole pool
(`seq_event + seq_thought`, minus `"idle"` keys) by raw cosine to the stance
question, keeps what clears `RELEVANCE_FLOOR = 0.45`, deduplicates with
`collapse()`, and hands the result to a new `allocate()`.

`allocate()` fills time bands relative to `scratch.curr_time`:

| Band | Age at probe time | Slots |
| --- | --- | --- |
| recent | ≤ 12 game hours | 8 |
| mid | 12–36 h | 7 |
| old | > 36 h | 5 |

`BANDS = (("recent", 12, 8), ("mid", 36, 7), ("old", None, 5))`; the slots sum
to `EVIDENCE_N - RESERVED_N = 20`, which CI asserts. Within a band, cosine
order, capped at `PER_TIMESTAMP_N = 3` per timestamp so a perception burst
cannot eat a band — after `collapse()`, distinct text at one timestamp is
typically the chat summary plus a perceived event plus a thought, so 3 lets all
three through. A band with nothing to put in its slots gives them back: a spill
pass re-admits deferrals in rank order while the budget and the cap still hold.
So banding changes *which* relevant memories are shown, never how many, and
early in a run — when everything is in one band — the result is exactly the
best 20 by cosine. `allocate()` returns `(kept, rejected, occupancy)`, and
`occupancy` reports the slots a band really used after spill, not the quota it
was promised.

Removing `new_retrieve` was not merely tidying. Asking it for `RETRIEVE_N = 90`
truncated the candidate pool by composite score, which is the exact bottleneck:
a relevant node at composite rank 91 of Luis's 1,679 was invisible. The call
also cost a second embedding of the stance question — `pool_relevance` and
`new_retrieve` both reach `extract_relevance` — plus a second full cosine scan
and `retrieve.py:260-264`'s per-node debug print. `RETRIEVE_N` is deleted.

### Utterance slots split 4/6, in dialogue order

`select_utterances()` gives `RECENT_UTTERANCE_N = 4` of the ten reserved slots
to the agent's most recent conversations and the remaining six to the existing
`rank_utterances()` across everything earlier. The grain is the conversation,
not the turn: `own_utterances` inherits every line's timestamp from the parent
chat node, so all turns of one conversation share a `created` and there is
nothing finer to rank them by. That is also why the recent slots fill in
dialogue order rather than by cosine — ordering by relevance put a reply ahead
of the line it answered.

No floor on utterances, and no utterance clause in the relevance gate. Measured:
utterance median cosine 0.24 against 0.51 for pool statements; only 61 of 431
utterances outscored the weakest statement already in a prompt, and for one
agent none of 97 did. The only rows a floor could touch in this run are
Marcus's, whose entire pool tops out at 0.40 — it would fix zero rows while
inventing an unmeasured threshold.

### Every reading records its own selection

Each reading carries a `selection` field, assembled from numbers
`pool_relevance()` already computed and previously discarded — **zero extra API
calls**:

```
"selection": {
  "memories": [{"id", "cos", "band", "created"}, ...],
  "quoted":   [{"cos", "created", "slot"}, ...],      # cosine only, no line text
  "rejected": [{"id", "cos", "reason"}, ...],         # top REJECTED_N = 5
  "bands":    {"recent": n, "mid": n, "old": n},
}
```

Rejection reasons: `below_floor`, `band_full`, `timestamp_cap`, `budget_full`.
`experiment_logger.log_opinions()` splats `**reading`, so no logger change was
needed. `dashboard.py::_opinions()` pops `selection` beside `evidence`, so the
polling payload does not grow.

### `last_accessed` persists

`ConceptNode.last_accessed` was set to `created` at construction, written by
retrieval, and never saved — so every resumed or forked run restarted the
recency clock for all nodes at once. `save()` now writes it, and the loader
restores it when present. Backward compatible by construction: an old
`nodes.json` has no such key and the constructor default fires. Round-trip
asserted in `check_retrieval.py`, which already owned both sides of `touch`.

This is a simulation-side fix; it does not change what the probe selects. It
does make offline replay exact, which dissolves a caveat
`sweep_reserved_slots.py` had documented independently.

### Label hygiene

| Before | After |
| --- | --- |
| `low_relevance` | `no_relevant_memory` |
| `asleep` | `asleep_night` / `asleep_daytime` (`NIGHT_FROM, NIGHT_TO = 22, 6`) |

`low_relevance` had become a lie: post-change `shown is None` and
`best < floor` are the same test, so the label can only mean one thing. The
sleep split exposes a planner defect — 28 agent-hours of scheduled mid-day
sleep, 13 of them one agent's — that was hiding inside the same label as 3 a.m.

No frontend change was needed: the chart lifts the pen on a null score, not on
the reason string.

### `is_asleep()` samples the hour, not the instant

The probe fires at the top of the hour, before the day's next action is
installed, so reading `act_description` withheld readings from agents who woke
twenty minutes later. `scratch.f_daily_schedule` is the whole decomposed day as
`[[task, minutes], ...]` and `get_f_daily_schedule_index(advance=N)` already
takes a forward look-ahead in minutes, so the coming hour can be read off the
schedule, every ten minutes, without waiting for it:

```python
reached = {persona.scratch.get_f_daily_schedule_index(advance=m)
           for m in range(0, 60, 10)}
tasks = [schedule[i][0] for i in sorted(reached) if i < len(schedule)]
return bool(tasks) and all(sleeping(task) for task in tasks)
```

Withheld only if **every** task in the hour is a sleep task. Read-only, no API
calls, no change to `reverie.py`'s step loop — the proposal predicted this would
need one; it did not. Falls back to `act_description` when `f_daily_schedule` is
still empty, the same guard `dashboard_bridge.py:204` uses.

## Measured against the predictions

Re-gating the finished run `stg-base_the_ville_datacenter_n8_private-3` offline
with the new rules (`scripts/replay_stance_prompt.py`, which now mirrors them),
cross-tabulated against what each row was logged as:

| Logged as | Still withheld | Now taken |
| --- | --- | --- |
| `asleep` (177) | 149 | **28** |
| `low_relevance` (31) | 10 | **21** |
| scored (176) | 3 | 173 |

- **The 28 recovered sleep readings match the prediction exactly**, spread
  across all eight agents (Elena 6, Aisha 5, Marcus 5, Maya 3, Luis 3, Denise 2,
  Tom 2, Rachel 2).
- Of the 31 `low_relevance` rows, **9 were genuinely below the floor** (Marcus,
  whose pool tops out at 0.400) and 22 were not — the mislabelling the proposal
  predicted. 21 of those 22 are now replayable; the 22nd is asleep for its whole
  hour and moves to a sleep label instead.
- **3 readings that were scored are now withheld**, all Aisha Rahman (Feb 14 at
  08:00, 11:00, 16:00), asleep at all six samples of each hour. The hour window
  cuts both ways, and these three were ratings taken of a sleeping agent.

So the proposal's headline 176 → 198 is right in its parts but not as a single
number, and the doc's own warning applies: **separate the counts by `withheld`
reason, not by total.** Offline, 194 of 384 rows are replayable (173 + 21); the
28 recovered sleep rows never measured relevance, so no cosine exists on disk to
gate them and they can only be counted live.

The `shown == best` invariant is now structural rather than something to verify
per row: the pool's closest memory clears the floor by definition and
`allocate()` can only reorder what is shown, never drop the top-ranked
candidate while slots remain.

## Determinism, re-taken under `rubric_v1`

§2.7 of the proposal measured "identical prompt → mean |Δ| 1.0, zero moves
≥ 15" on the direct scorer that `rubric_v1` replaced, so that figure did not
carry. Re-taken the same way: the first 20 rows of
`stg-base_the_ville_datacenter_n8_private-3` replayed twice through
`scripts/replay_stance_prompt.py` at `temperature=0`, 40 calls, same rows in
the same order both passes.

**The scale is exactly deterministic. The decision to use it is not.**

- 11 rows produced a score in both passes. **Every one identical** — mean
  |Δ| 0.0, zero moves ≥ 15. Strictly better than the 1.0 the old scorer gave.
- **2 of 20 flipped across the usable/unusable boundary**: Denise Brooks at
  step 2880 (no score → 30) and Rachel Nguyen at step 3600 (30 → no score).
  The null count was 8 in both passes, but not the same 8 rows.
- 5 of 20 rationales differ in wording even where the score is identical,
  which is expected and harmless — nothing reads the rationale as data.

So a before/after comparison of **scores** under `rubric_v1` is attributable:
an identical prompt gives an identical number. A before/after comparison of
**how many readings the model declines** is not, because roughly a tenth of
rows sit on that boundary and can fall either way on identical input. Count
withheld readings by the probe's own reasons — which are deterministic
functions of memory and the clock — and treat `abstained` as noisy.

All 8 nulls were explicit abstentions, "The record does not establish a
position", not parse failures. Every one of them had exactly 2 statements of
evidence, against 1-3 on the rows that scored. These replays run on the *old*
selection's prompts, which is precisely the thin evidence this change exists to
fix, so the abstention rate should fall as the prompts fill — that is a
prediction, not a measurement, and the number to check it against is the
`abstained` count on the next full run.

Everything in the section above this one counts selection decisions rather than
scores, so none of it depends on any of this.

## Verification

Green: `test_stance_rubric.py` (17 tests, 12 pre-existing), `check_opinion_probe`,
`check_retrieval`, `check_memory_categories`, `check_dashboard_js`, `check_repo`,
`check_stance_graph.js`, `manage.py test translator` (23, one added),
`manage.py check`.

The added Django test hits `/dashboard/run/<sim>/` with a reading that carries
both `evidence` and `selection` and asserts the payload has neither while the
log keeps both — the payload-size question in §3.4 of the proposal, answered by
a test rather than by inspection.

New CI rules, in place of two that the change invalidated:

- the `new_retrieve(... touch=False)` source grep is replaced by one that flags
  any `new_retrieve` call in `opinion_probe.py` lacking `touch=False` —
  vacuously satisfied now, non-vacuous the moment retrieval is reintroduced
- the band slots must sum to `EVIDENCE_N - RESERVED_N`, the oldest band must
  have `limit is None`, `0 < RECENT_UTTERANCE_N < RESERVED_N`,
  `PER_TIMESTAMP_N > 0`
- the `RETRIEVE_N > EVIDENCE_N` rule is deleted with the constant
- `check_retrieval.py` round-trips a saved node through `nodes.json` and asserts
  both that `last_accessed` survives and that a file without the key falls back
  to `created`

The teammate's `test_stance_rubric.py` was edited: three assertions changed
vocabulary, one `touch=False` assertion became a stronger direct check that
`last_accessed` is unmodified, and five tests were added (selection logging,
band spill, the per-timestamp cap, quote ordering, the hour window). One
assertion in it had been vacuous — `patch.object(..., "new_retrieve",
create=True)` on an attribute that no longer exists makes
`assert_not_called()` always pass.

## Where the offline tools moved

- `replay_stance_prompt.py` — gates on the new labels; `sleeping_through_hour()`
  mirrors the hour window from the movement files, deriving the window from the
  run's own `sec_per_step` rather than assuming an hourly cadence; falls back to
  `relevance.best` where `shown` is null, which is sound precisely because the
  new selection makes them the same number; counts `relevance_unrecorded`
  separately rather than calling an unmeasured row `no_relevant_memory`.
- `sweep_reserved_slots.py` — rebuilds quotes through `select_utterances` and
  ranks the pool through cosine + `allocate` instead of taking the log's order.
  Its ranking is now exact, where the composite could not be recomputed after
  the fact: cosine needs only `embeddings.json` and the bands only `created`.
  The candidate set is still the logged ids, so a sweep sees no more evidence
  than the original reading had.
- `analyze_stance_evidence.py` — the `channel` verdict now counts quoted lines.
  It was computed from `chat_event` + `planning` ids only and reported
  **DROPPED** for four of eight agents whose conversations reached the prompt
  through the quoted stream. On the measured run: 36 cited chat/planning nodes
  against 1,588 quoted lines, and no DROPPED verdict survives.

## Deviations from the plan

1. **5a was not landed separately before steps 1–2.** The plan split it into
   5a-i (log cosines under the old selection, for a "before" snapshot) and
   5a-ii. The before cosines are obtainable offline from `nodes.json` plus
   `embeddings.json`, so a separate landing would have bought nothing and cost
   a re-run of a game day. The `selection` field shipped complete, in one
   landing, with steps 1–2.
2. **The sleep fix needed no change to `reverie.py`'s step loop**, which the
   proposal predicted it would.
3. **5b is two edits, not three.** All three `add_*` methods already return the
   node, so neither `ConceptNode.__init__` nor any `add_*` signature changed.
4. **§3.4 of the proposal was wrong** that the dashboard payload would not grow:
   `_opinions()` strips only `evidence`. `selection` is now popped beside it.
5. **Two costs the proposal did not name:** a CI regex rule and one of the
   teammate's test assertions both break on removing `new_retrieve`; both were
   replaced with strictly stronger checks.
6. `select_utterances` skips `rank_utterances` when nothing is left to rank —
   otherwise an agent who has not spoken still pays an embedding call for the
   stance question.
