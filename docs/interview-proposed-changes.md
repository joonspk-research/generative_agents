# The interview feature: how it works, and proposed changes

**Status: proposal. Nothing in here has been implemented.** Written to be read
by someone who has not been following the probe work, so the decision can be
discussed before any code changes.

The interview is the dashboard's qualitative instrument: pick an agent, ask it a
question in natural language, read its answer. It is the companion to the stance
graph, which is the quantitative one. The graph was audited and corrected over
several rounds (see
[belief-change-cast-and-probe-log.md](belief-change-cast-and-probe-log.md) and
[own-words-evidence-decision-trail.md](own-words-evidence-decision-trail.md));
the interview was not, and it is still largely Stanford's original code path,
which was written for qualitative demos rather than for measurement.

**What is being asked for:** sign-off on which of the seven changes in §4 to
make, and answers to the four open questions in §6. The changes are independent
of each other and can be taken in any subset.

---

## 1. How it works today

| Stage | Where | What happens |
|---|---|---|
| 1. UI | `dashboard.html:1237-1244` | Sends the literal string `call -- interview <Agent> ;; <question>` |
| 2. Queue | `dashboard_bridge.py` `CommandFeed` | Dashboard commands and terminal input merge into one queue. Only processed while the run is idle, so you cannot interview mid-run |
| 3. Dispatch | `reverie.py:786-812` | Splits on `;;`, looks up the live `Persona`, keeps per-agent history in `self._interviews` (memory only). `;; end_convo` clears it |
| 4. Safety | `run_gpt_generate_safety_score` | One API call per question; a score of 8 or more refuses to answer |
| 5. Retrieval | `new_retrieve(persona, [line], 50, touch=False)` | Top 50 memories by recency + relevance + importance, equally weighted |
| 6. Compress | `generate_summarize_ideas` → `v3_ChatGPT/summarize_ideas_v1.txt` | Those 50 are compressed into **one summary paragraph** |
| 7. Answer | `generate_next_line` → `v2/generate_next_convo_line_v1.txt` | Prompt = full `get_str_iss()` + the entire prior transcript + that one paragraph. `temperature: 1`, `max_tokens: 250` |

Two details of stage 7 matter later. The template ends with `!<INPUT 7>!: "` —
an open quote, written for a completion model that would close it — and the
response cleanup is `gpt_response.split('"')[0].strip()`.

The answer is returned as the command's result, printed to the terminal, and
appended to `temp_storage/dashboard/results.jsonl`. The UI rebuilds the visible
transcript from that file.

## 2. What is already correct

The one previously known interview bug is fixed and guarded. Interviewing an
agent used to hand the 50 memories behind its answer a fresh `last_accessed`
stamp, so observing an agent changed what it retrieved next (recorded as Bug 1
in [memory-inspection-engineering-log.md](memory-inspection-engineering-log.md),
and again as §1.6 of [stance-graph-engineering-log.md](stance-graph-engineering-log.md)).
`touch=False` fixes it, and `check_retrieval.py:193-215` parses `reverie.py` and
fails if any `new_retrieve` call inside `open_server` omits it.

Nothing in the interview path writes to agent state. That invariant holds and
should be preserved by every change below.

## 3. Findings

Each is labelled by how it was established. **Measured** = observed in live
calls or read off saved run data. **Mechanical** = a property of the code that
is certain without running it. **Latent** = predicted from the code, not
observed.

### 3.1 The interview cannot see anything the agent said (measured)

`new_retrieve`'s candidate pool is `seq_event + seq_thought` (`retrieve.py:232`).
`seq_chat` is absent, under Stanford's own note that the raw conversation could
be retrieved too, "but for now". So conversations are unreachable: Maya has 15
on disk and none can be retrieved. Asked *"Who have you talked to about the
datacenter, and what did you say?"*, retrieval returned `{'thought': 42,
'event': 8}`, and the answers were:

| | the answer named | who the agent actually talked to |
|---|---|---|
| Maya Okonkwo | Denise Brooks, Marcus Williams | Aisha **6**, Denise 5, Elena 2, Marcus **1**, Luis 1 |
| Elena Chen | Rachel Nguyen only | Maya **2**, Rachel 1, Denise 1, Aisha 1 |

No invented people, but both omitted their most frequent partner and
foregrounded a single-conversation one, and neither quoted anything it had
actually said. The account is reconstructed from reflection *about*
conversations. It reads like recall and is not.

This is the same defect that was found and fixed in the stance graph. Fixing it
there is what restored the graph's ability to register support at all.

### 3.2 No time information reaches the model (mechanical)

`generate_summarize_ideas` builds its statements as `f"{n.embedding_key}\n"` —
the text only, no `created`. The answer template has no time input either. So
the interview cannot tell this morning from three days ago, and cannot say "I
used to think X." For an instrument whose purpose is probing belief *change*,
this is the most consequential gap. The stance probe dates every statement and
sorts them chronologically; the interview discards all of it.

### 3.3 The full identity stable set is in every prompt, and it states the stance (measured)

`get_str_iss()` is 1,239–1,368 characters per agent across the eight, carrying
innate and learned traits, values, personal stake, persuadability, `currently`,
and the daily plan requirement. Maya's includes:

> *Personal stake: her next funding round depends on being near serious compute,
> and she has already told her investors the Ville can be that.*
>
> *Currently: ...has been telling people about the jobs figure in it. She has
> not looked closely at the water or the rate sections.*

Against that, 50 memories arrive as a single paragraph. Every field of the ISS
was **byte-identical** before and after a full game day, because
`revise_identity` (`plan.py:413`) only rewrites `currently` and `daily_req` at
day boundaries. So Maya spent the day discussing the water figure with Aisha and
her prompt still asserted she had not looked at it.

This is not automatically a bug — an interview is role-play with a character,
and a character should know itself. It is a validity limit: an interview answer
is partly the seed description being read back, so it is not independent
evidence that anything changed. `stance_iss` in `run_gpt_prompt.py` documents
why the stance probe was cut back to name and age for exactly this reason, and
notes the second-order problem that across days `currently` drifts from the
agent's own reflections, which are already in the retrieval pool.

Caveat: the byte-identical finding is from a single-day run. Static *within* a
day is verified; the multi-day drift is read from the code, not observed.

### 3.4 No relevance floor and no deduplication (measured)

Asked *"What is your favorite colour?"*, retrieval still returned 50 datacenter
memories, the summarizer produced datacenter content, and Maya answered *"blue…
aligns closely with my vision for the datacenter."* Every question is answered
through the datacenter, because the top 50 by composite score barely changes
with the question. A control question is therefore not possible.

Unique `embedding_key`s among the 50, over seven measured calls: 32, 35, 39, 47,
47, 48, 48. So up to 36% of the retrieved context is duplicate text. The stance
probe's `collapse()` has no equivalent here.

### 3.5 The response cleanup can destroy the answer (mechanical; latent in practice)

`split('"')[0].strip()` applied to plausible responses:

```
'I said "we need the water figures" and she agreed' -> 'I said'
'"I think it is fine."'                             -> ''
'TOKEN LIMIT EXCEEDED'                              -> 'TOKEN LIMIT EXCEEDED'
```

In 7 live calls this never fired: the model closed the template's open quote at
the end and the cleanup correctly stripped just that one character. So it is
**latent, not observed** — but any answer containing a quotation mark loses
everything after it, which is likeliest on precisely the questions a researcher
asks about conversations.

Two things make it worse. `__func_validate` cannot return `False` (it only
wraps the cleanup in `try/except`, and string splitting does not raise), so
`safe_generate_response`'s `repeat=5` never retries and an empty answer is
accepted. And `GPT_request` returns the string `"TOKEN LIMIT EXCEEDED"` on any
API error, which passes that validator and would be displayed to the user as the
agent's own words.

### 3.6 Reproducibility and truncation (mechanical)

`temperature: 1`, so the same question to the same unchanged agent gives
different answers and an interview cannot be replayed. The stance probe uses
`temperature: 0` for this reason. `max_tokens: 250` against measured answers of
roughly 160–200 tokens, with no `finish_reason` check anywhere, so answers will
occasionally be cut mid-sentence with no indication.

### 3.7 Interviews are not part of the run's data (read from code)

The whisper branch logs to the experiment logger (`midrun_whisper`), and the
probe writes `experiment/opinions.jsonl`. The interview branch logs nothing.
Interview content exists only in `temp_storage/dashboard/results.jsonl`, with
wall-clock time, no step, no game time, and no record of which memories were
behind the answer. For a run you intend to write up, the qualitative instrument
leaves nothing in the run's own data.

### 3.8 Smaller items (read from code)

- **No `is_asleep` check.** The probe withholds a reading from a sleeping agent;
  the interview will answer at 03:00.
- **Display can desync from the agent's context.** The UI rebuilds the
  transcript from the last 400 lines of `results.jsonl` sliced to 60 rows
  (`translator/dashboard.py:253`), shared with every other command for that sim,
  while the backend's `self._interviews` is unbounded. A long session can drop
  early turns from the display while the agent is still being prompted with
  them. The agent's context is the authority; only the display is wrong.
- **A dead path carries the old leak.** `converse.open_convo_session` (via
  `Persona.open_convo_session`) is unreachable now that `call -- analysis` only
  prints a usage hint, and its `new_retrieve(persona, [line], 50)` at
  `converse.py:271` still defaults to `touch=True`. Harmless while dead, a trap
  if anyone re-enables it, and the CI guard only inspects `open_server`.
- **Debug noise.** `run_gpt_prompt.py:2519` prints
  `asdhfapsh8p9hfaiafdsi;ldfj as DEBUG 16` on every interview question.
  Stanford's, pre-existing.

## 4. Proposed changes

None of these touch agent cognition: all of them are on the observer side, and
every one must keep `touch=False` and write nothing to agent memory.

### P1 — Give the interview the agent's own words

**Fixes 3.1.** Reserve a fixed number of the evidence slots for the agent's
actual spoken lines, ranked by cosine against the question asked, and pass them
to the answer prompt **as verbatim quotes, bypassing the summarizer** — routing
them through `generate_summarize_ideas` would paraphrase away the only thing
they are there for.

Reuses `opinion_probe.own_utterances` and `rank_utterances`, which already do
this for the stance probe. `rank_utterances` currently hardcodes
`STANCE_QUESTION` and would need a focal-point argument — a change to a function
the probe depends on, so the probe's CI guards have to be re-run.

- Touches: `reverie.py`, `opinion_probe.py`, a new version of the answer
  template.
- Cost: one extra embedding per distinct question, plus one per utterance until
  cached (`opinion_probe.embed` caches in-process).
- Risk: medium — it is the largest change, and the right number of reserved
  slots for an interview is not the 10 the probe measured for a rating.
- Verify: re-ask "who have you talked to" and check the named partners against
  `seq_chat`, which is the measurement in 3.1 and is cheap to repeat.

### P2 — Put time back in

**Fixes 3.2.** Date every statement given to the summarizer, date the quoted
lines, and add the current game time to the answer prompt. Needs a new template
version with an extra input (the repo's practice is to version prompts, as with
`datacenter_stance_v1/v2`, not to edit in place).

- Touches: `converse.py`, a new answer template, `run_gpt_prompt.py`.
- Cost: none beyond slightly longer prompts.
- Risk: low.
- Verify: ask "when did you first hear about the datacenter?" and check the
  answer against the node timestamps.

### P3 — Fix the cleanup and the validator

**Fixes 3.5.** Strip at most one matched leading/trailing quote pair instead of
splitting on the first quote; make `__func_validate` reject an empty answer and
the `"TOKEN LIMIT EXCEEDED"` sentinel so the existing retry loop actually
retries; raise `max_tokens` and surface a truncated answer rather than hiding it
(3.6).

- Touches: `run_gpt_prompt.py`.
- Cost: none, except retries that previously did not happen.
- Risk: low. Worth a CI guard, negative-tested, asserting the validator rejects
  both cases.

### P4 — Log interviews into the run's data

**Fixes 3.7.** Mirror the whisper branch: one `experiment_logger.log_event` per
turn with step, game time, agent, question, answer, the evidence node ids, and
how many quoted lines went in. That last field is what would let anyone check
later whether an answer was grounded or reconstructed.

- Touches: `reverie.py`, possibly `experiment_logger.py`.
- Cost: none.
- Risk: low. It does add a row type to run data, which is a decision (§6).

### P5 — Filter and deduplicate the retrieved 50

**Fixes 3.4.** Apply `collapse()` and a relevance floor to the retrieved
statements, as the stance probe does.

- Touches: `reverie.py` or a small helper beside it.
- Cost: none.
- Risk: medium, and this is the one place where the probe's numbers do **not**
  transfer. `RELEVANCE_FLOOR = 0.45` was calibrated against a fixed stance
  question; an interview question is arbitrary, and too high a floor would
  starve legitimate off-topic questions instead of merely making them honest.
  Suggest shipping `collapse()` first, measuring question-to-statement cosines
  across a set of questions, and setting the floor from that.

### P6 — Make interviews reproducible

**Fixes 3.6.** `temperature: 0`.

- Risk: low mechanically, but it is a judgement call, not an obvious win — a
  single deterministic answer per question may read as less natural. See §6.

### P7 — Small corrections

Record `asleep: true` rather than refusing (3.8); raise the UI's result window
or serve the transcript from `self._interviews` instead of rebuilding it from
the command log (3.8); extend `check_retrieval.py`'s `touch=False` rule to cover
`converse.open_convo_session` so the dead path cannot come back as a live leak
(3.8).

## 5. Suggested order

| Phase | Changes | Why this order |
|---|---|---|
| 1 | P3, P4 | Small, independent, no judgement calls. P4 first also means every later change is measurable from run data rather than from ad-hoc scripts |
| 2 | P2 | Needed before P1 is worth much — quoted lines without dates cannot show change |
| 3 | P1 | The substantive fix. Verifiable by the 3.1 measurement |
| 4 | P5, P6, P7 | P5 needs calibration; P6 and P7 are preference and tidying |

## 6. Open questions

1. **Should the interview keep the full ISS?** Keeping it is defensible — it is
   role-play, and the character should know itself — but then an interview
   answer is partly the seed read back and cannot be cited as independent
   evidence of change. Options: keep it and state the limitation; cut it back as
   the stance probe did; or run both once and compare. A middle option worth
   considering is keeping the traits but dropping `currently`, which is the field
   that goes stale within a day and double-counts reflections across days.
2. **Should interviews go into `experiment/`?** It adds a row type to run data
   and makes interview content part of the record, including any question asked
   carelessly.
3. **`temperature: 0` or leave it at 1?** Reproducibility against naturalness.
   Note a replay harness only works at 0.
4. **How many reserved slots for quoted lines (P1)?** The probe measured 10 of
   30 for a fixed rating question. An interview has an arbitrary question and a
   summary paragraph rather than a statement list, so the number should be
   measured again rather than inherited.

## 7. Deliberately not proposed

| Not proposed | Why |
|---|---|
| Adding `seq_chat` to `new_retrieve`'s pool | It is read by planning, conversing and reflecting, so it would change agent behaviour, not just the observer. The probe reads chat nodes itself for this reason |
| Changing `revise_identity` | It is part of agent cognition. 3.3 is about what the *interview* is shown, not about how the agent maintains itself |
| Deleting `open_convo_session` or the debug print | Pre-existing Stanford code; flagged in 3.8, left alone |
| An extraction pass over the quoted lines | Built and measured as a null for the stance probe (§11.7 of the probe log). No reason to expect a different result here |

## 8. How the findings were produced

Throwaway scripts, currently in `/tmp` and not committed — they can be promoted
to `scripts/` if this work goes ahead:

- `/tmp/probe_interview.py` — replicates `reverie.py:806-812` against a saved
  persona and prints the retrieved composition, the summary, the **raw** model
  response and the cleaned answer side by side.
- `/tmp/check_interview_claims.py` — prints `get_str_iss()`, the real `seq_chat`
  partners and the agent's actual spoken lines, which is what 3.1 checks the
  answers against.

Run from `reverie/backend_server`, against
`stg-base_the_ville_datacenter_n8_private-2`.

**Confidence boundary.** §3.1, §3.3 and §3.4 rest on 8 live calls against two
agents in one saved single-day run, and §3.3's static-ISS result cannot show
multi-day drift. §3.2, §3.5, §3.6, §3.7 and §3.8 are properties of the code and
hold regardless. Nothing here has been checked against a fresh run.
