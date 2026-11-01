# Stance graph: engineering log

Why each change was made, what it replaced, and the evidence it is right.
For *where* the changes live, see
[stance-graph-change-map.md](stance-graph-change-map.md).

The dashboard's two windows into an agent's memory — the Interview and the Mind
tab — have their own pair:
[memory-inspection-engineering-log.md](memory-inspection-engineering-log.md) and
[memory-inspection-change-map.md](memory-inspection-change-map.md). §1.6 and
§5.1 below are summaries of work recorded in full there.

All measurements below come from one run:
`stg-base_the_ville_datacenter_n8-2` — 8 agents, one simulated day
(Feb 13 2023, 00:00–24:00), `gpt-4o-mini`, 192 stance readings,
16 conversations, 32 reflections.

---

## 0. What was built

A per-agent line graph at the bottom of the dashboard showing where each of the
8 residents stands on the proposed datacenter, from 1 (against) to 100 (in
support), read once per game hour and persisted so the line continues when the
sim is resumed. Each reading carries the model's one-sentence reasoning and the
memory ids it was based on. Conversations, mid-run whispers and reflections are
marked on the lines at the timestamp they happened, so a move in a curve can be
traced to the thing that caused it, and a conversation marker clicks through to
its transcript.

The work came in four stages, in this order and for this reason:

1. **Fix retrieval** (§1). The graph's y-value is produced by the same
   retrieval machinery the agents use to think. Graphing first would have
   faithfully plotted a wrong number.
2. **Build the probe and the graph** (§3).
3. **Mark the events that explain the curve** (§4).
4. **Cross-verify the two things a reader would reasonably doubt** (§3.2, §5).

---

## 1. Retrieval bugs fixed first

### 1.1 Recency scored list position instead of elapsed time

`extract_recency` built one decay value per *slot*:

```python
recency_vals = [persona.scratch.recency_decay ** i
                for i in range(1, len(nodes) + 1)]
for count, node in enumerate(nodes):
    recency_out[node.node_id] = recency_vals[count]
```

`new_retrieve` passes its candidates sorted by `last_accessed` **ascending**, so
the oldest memory sat at index 0 and received `decay ** 1` — the *highest*
recency score — while the just-accessed memory at the end received the lowest.
The recency component was ranked backwards.

The paper defines recency as exponential decay over the number of sandbox game
hours since a memory was last accessed. The fix computes that directly per
node, which also makes the score independent of the order candidates arrive in.

**Guard:** `check_retrieval.py` asserts the exact value for 48 / 10 / 1 / 0
hours elapsed, that the ranking is freshest-first, and that shuffling the input
list does not change any score.

### 1.2 Retrieval weights were [0.5, 3, 2]

The live weights tripled relevance and doubled importance while halving
recency. The paper weights all three components equally; three alternative
weight lines sat commented out in the file. Set to `[1, 1, 1]` (your call).

**Guard:** `check_retrieval.py` parses `gw` out of `retrieve.py` and requires
`[1, 1, 1]`.

### 1.3 Reflection's focal-point window used a counter that did not match the list

`generate_focal_points` filters idle records out of the node list, then sliced
it with a counter that *includes* idle records:

```python
nodes = [... if "idle" not in i.embedding_key]       # idle removed
for node in nodes[-1 * persona.scratch.importance_ele_n:]:
```

`importance_ele_n` counts every perceived event, idle ones included, so the
window size bore no relation to the list being indexed. Worse, it is reset to
`0` on every reflection, and `nodes[-1*0:]` is `nodes[0:]` — **the entire
memory stream**. So the first reflection after a reset asked its questions
about everything the agent had ever perceived.

Separately, the list was sorted by `last_accessed` while the unpacking variable
was named `created` — so the window drifted as memories were read, not as they
were formed.

Fix: a named constant `FOCAL_POINT_RECORDS = 100` (the paper's window) and a
sort by `created`, which is what the variable name already claimed.

**Guard:** `check_retrieval.py` feeds 150 events plus 25 idle ones and asserts
the prompt received exactly the 100 most recently *created* non-idle records.

### 1.4 The `recency_decay` default disagreed with the paper and with our own seeds

`scratch.py` hardcoded `0.99`; the paper uses `0.995`, and so does every
persona seed shipped in this repo. Set to `0.995`.

> **Gotcha worth knowing before you read any default in `scratch.py`:** a saved
> persona's `bootstrap_memory/scratch.json` **overrides** these defaults, so the
> constants in `scratch.py` only ever apply to a persona created without one.
> Our seeds already carried `0.995`; this change only removed the disagreement.
> The same mechanism explains §5.

### 1.5 A read-only retrieval had no way to leave memory alone

Found while designing the probe, fixed in retrieval. `new_retrieve` stamped
`last_accessed = curr_time` on every node it returned. That is correct for an
agent's own retrieval — thinking about something *is* accessing it — and fatal
for a measurement: the probe reads the 30 memories most relevant to the
datacenter every game hour, so stamping them would reset the recency clock on
exactly those memories and push them to the top of the agent's next retrieval.
The graph would have been steering the run it was measuring.

Added `touch=True` as a parameter; the probe passes `False`.

**Guard:** `check_retrieval.py` asserts both halves — `touch=False` leaves
`last_accessed` untouched, **and** the default still stamps it (otherwise the
agents' own recency would quietly stop working). `check_opinion_probe.py`
asserts the probe actually passes `touch=False`.

### 1.6 The dashboard interview had the same leak, through a different door

Found later, while tracing what the Interview tab writes. The interview is
stateless about memory *content* — it never calls `add_thought`, nothing
reaches `nodes.json`, and `self._interviews` dies with the process — but it
answers by running a real retrieval against the question asked, and that call
took the default `touch=True`. Asking an agent about the datacenter therefore
stamped the 50 memories behind its answer, handing them a recency score of 1
in every retrieval the agent made afterwards, in `plan.py`, `reflect.py` and
`converse.py`. §1.5 exactly, reached from the UI instead of the step loop.

`last_accessed` is not serialized (`associative_memory.save` omits it, and
`Node.__init__` resets it to `created`), so the perturbation was bounded to
the live process — which is also the only place a run happens.

Interviews now retrieve with `touch=False`. The observer can read the memory
that produced an answer without promoting it.

**Guard:** `check_retrieval.py` walks `open_server` with `ast` and requires
`touch=False` on every `new_retrieve` a console command makes, rather than
naming the interview specifically — the next read-only command should inherit
the rule instead of re-finding the bug. It also fails if no command retrieves
at all, so the rule cannot pass by matching nothing.

---

## 2. Examined and deliberately not changed

Recorded so nobody re-investigates these from scratch.

| Question | Finding | Decision |
|---|---|---|
| Should retrieval return chat memos or the raw chat? | Both are stored; the memo is the agent's own summary, the `chat` node is the transcript. Current behaviour matches the paper closely enough. | Unchanged |
| Should idle nodes decrement the reflection trigger? | They do, by 1 each (`generate_poig_score` returns 1 for "is idle"). Arguably they should not. | Unchanged — behavioural change, out of scope of the graph |
| Should thoughts and whispers decrement it? | They do not; only perceived events do. The paper is ambiguous. | Unchanged, flagged |
| Is memory bounded? | No. Unbounded here; the paper does not bound it either. | Unchanged |
| `importance_ele_n` after §1.3 | Now written but never read — dead state. | Left in place (pre-existing; removing it changes the saved-persona schema) |
| Payload row caps | `conversations` and `events` are fed 300 rows, `opinions` 4000. A run with >300 conversations would keep extending the line while early markers silently drop. | Flagged; this run has 16 |
| `planning_thought_on_convo_v1.txt` | Hardcodes "her planning" for every agent. | Flagged, unrelated to this work |

---

## 3. The stance graph

### 3.1 Decisions

| Decision | Alternative | Why |
|---|---|---|
| Scale 1–100 | 1–10 (the original) | A 10-point scale cannot hold a conditional position. This surfaced concretely: Luis read 3 before his 14:00 conversation with Marcus (who read 1) and 7 after, which looked like the conversation had flipped him. On a 10-point scale "supports it if local hire is guaranteed" has to pick 3 or 7 and then flips between them hour to hour while the underlying belief never moves. |
| No anchor list in the prompt | Spelling out "1 — against, 3 — leans against, 5 — torn…" | With anchors, `gpt-4o-mini` used **only those six values across all 192 readings** and nothing else. The prompt now says any number is available, not to round to multiples of 5 or 10, and that a settled position belongs in the first or last ten. |
| `temperature=0`, passed explicitly | Inherit the `chat_completion` default | `ChatGPT_request` ignores the `gpt_param` dict every other prompt builds, so without this the readings sample at the default and two reads of an *unchanged* memory set disagree. A flat line has to mean "nothing moved", not "the sampler was quiet". This is the only prompt in the codebase that passes its temperature through. |
| A failed parse logs `None` | Fall back to a midpoint | Every other rating here falls back on failure (poignancy returns 4). A fabricated 50 would be indistinguishable from an agent that is genuinely torn. The graph draws a **gap** instead, and the raw unparseable answer is kept in the row. |
| Every row records its own `scale` | Assume the current scale | The scale already moved once (10 → 100). Old rows render against `STANCE_OLD_SCALE` and the tooltip says "(old scale)", so pre-change history stays truthful instead of being silently rescaled. |
| Evidence oldest-first and dated | Retrieval's own rank order | Retrieval returns by score, so the model got a shuffled undated list and could not tell what the agent thought an hour ago from a day ago — the one distinction a trajectory graph exists to show. The prompt also says to rate the position held *at the end* of the memories, not their average. |
| Probe every 360 steps (1 game hour), `0` = off | 10 minutes of game time | Your call. Settable live from the dashboard, same path as `autosave_steps`. |
| Synchronous, inside the step loop | A background thread | Your call: no interleaving with the agents' own LLM calls, no partial rows. |
| Billed separately | Count it as step cost | `usage.context` is tagged `source="opinion_probe"`, so measurement cost never inflates the cost of a step. |
| Node ids stored, stripped from the payload | Ship them to the browser | What makes a move explainable after the fact, without bloating every poll. |
| `call -- probe now` console command | Wait for the next hour | Lets you catch a before/after around a whisper. |

### 3.2 Cross-verification: does the probe change the run it measures?

**No.** Measured on the real `Persona` object for Luis Hernandez (751 nodes),
not on a mock:

| Checked | Result |
|---|---|
| Every saved memory file | byte-identical before/after |
| `last_accessed` on the 30 retrieved nodes | 0 moved |
| Nodes added or removed | 0 |
| `seq_event` / `seq_thought` / `seq_chat` | 661 / 84 / 6, unchanged |
| Keyword strengths, embedding cache | unchanged (279 keys) |
| `scratch` (`importance_trigger_curr`, `importance_ele_n`, `curr_time`) | unchanged (108, 91, 23:59:50) |
| LLM calls | exactly 1 chat + 1 embedding, `temperature=0` |
| **Non-vacuity:** same probe with `touch=True` | moves 30 nodes — the guard is load-bearing |

Side effects that *do* exist, stated plainly: the probe spends API budget
(tagged `source="opinion_probe"`), and it appends a row per agent to
`opinions.jsonl`. Neither is in any agent's memory.

---

## 4. Event markers

A line that moves without a visible cause is hard to trust. These mark what
reached an agent from outside, or what the agent did with what it already had,
directly on that agent's line at the step it happened.

| Marker | Source | Interaction |
|---|---|---|
| ▲ conversation | `conversations.jsonl`, one marker on **each** of the two speakers' lines | hover shows partner + summary; **click** opens the transcript |
| ◆ whisper | `events.jsonl`, `event_type == "midrun_whisper"` | hover shows the whisper text |
| ■ reflection | `events.jsonl`, `event_type == "reflection"` | hover shows the most poignant insight + "and N more insights at this moment" |

Decisions inside that:

- **Seed whispers are excluded.** All 40 `history_whisper` rows sit at step 0,
  before the first reading: they are the starting position, not something that
  happened during the run. They stay listed in the Whispers pane.
- **Reflections were initially excluded, then added.** The first scoping
  rejected them on a count I had got wrong (I reported ~596 reflections, i.e.
  3–4 glyphs between every pair of readings, which would have buried the
  curve). The real figure is **32 reflection episodes**; the 539 is the number
  of insight *nodes* those episodes wrote. See §5 for how they are counted.
- **One marker per reflection episode, never per insight.** A reflection writes
  up to 15 thoughts at a single timestamp, which would stack 15 identical
  glyphs on one x-position. `run_reflect` logs once, after both insight loops,
  with the most poignant insight as the label and the batch size in `extra`.
- **Reflections are filtered out of the Whispers pane and its count** — they
  share `events.jsonl` with whispers but are the agent's own thinking, not
  something whispered in. The count stays 41 (40 seed + 1 mid-run), not 73.
- **Markers sit on the line by interpolation** between the two scored readings
  that bracket their step, using the same `py(score, scale)` as the line
  itself. A marker outside the plotted span, or inside a gap left by a `None`
  reading, is dropped rather than clamped to the edge — there is no line there
  to attach it to.
- **Shape carries the event type, colour carries the agent**, since colour is
  already spent on identity.
- **Hit-testing is shared.** One `stanceNearest()` does the
  `createSVGPoint` / `getScreenCTM().inverse()` math for hover and click both.
  It honours the `selected` agent, which is what fixed the original complaint
  that hovering near a crossing reported a different agent's reasoning. The
  tooltip is custom rather than a native `<title>` because `<title>` has a ~1s
  browser delay.
- **The opened transcript survives a repaint.** `paint()` replaces
  `innerHTML` whenever the HTML changes, so setting `details.open = true`
  imperatively would snap shut on the next ~2s poll. The open state is instead
  keyed by `openConvo` (`step|speaker|speaker`) and rendered *into* the markup,
  which keeps `paint()`'s identical-HTML short-circuit working.

**Guard:** `check_retrieval.py` parses `run_reflect` with `ast` and fails if the
reflection log call is missing, or if it sits inside any loop. (The first
version of this guard was a string-index comparison that did **not** catch the
failure it was written for; the AST version was proven by deliberately moving
the call into the insight loop and watching CI go red.)

---

## 5. Cross-verification: why 32 reflections, not 2 a day?

The paper's claims, verbatim from `arxiv.org/html/2304.03442v2`: threshold
"150 in our implementation", 3 focal questions × 5 insights, and "our agents
reflected roughly two or three times a day".

Our run: **32 reflection episodes in one simulated day** across 8 agents —
Maya 7, Marcus 6, Denise 4, Luis 4, Aisha 3, Rachel 3, Tom 3, Elena 2. So
2–7 per agent per day against the paper's 2–3: the high end, not a different
order of magnitude.

**The trigger arithmetic is exactly as implemented.** `perceive.py` subtracts
each new event's poignancy from `importance_trigger_curr`, and
`reflection_trigger` fires at `<= 0`. Replaying that arithmetic over each
agent's stored events at the threshold the personas actually use reproduces the
observed count **exactly for all 8 agents**. At 150 it would predict 4–13.

The threshold the personas actually use is **250**, not the 150 in
`scratch.py` — it comes from the `scratch.json` in each persona's
`bootstrap_memory`, inherited from Stanford's shipped `base_the_ville_n25`
seeds (verified: all 25 of those carry `importance_trigger_max: 250`). Saved
state always wins over the code default (§1.4).

So the remaining spread is **event volume**, not configuration: Maya perceives
954 events totalling 1979 poignancy → 7 reflections; Elena 385 events / 737
poignancy → 2. Eight agents arguing about one proposal in a small town perceive
each other constantly.

**How to count reflections from `nodes.json`** — the classification that
produced the 32, since `type == "thought"` covers three different things:

| `filling` | Meaning |
|---|---|
| exactly 1 entry, pointing at a `chat` node | post-conversation planning/memo thought (`reflect.py`) — **not** a reflection |
| non-empty, otherwise | a reflection insight |
| empty | whisper or seed identity thought |

All insights from one reflection share a single `created` timestamp, so
**count distinct timestamps, not nodes.** 539 insight nodes / 32 episodes =
16.8 per episode (3 questions × 5 insights, plus retries). The other thought
nodes in that file: 64 post-conversation, 48 whisper/identity.

### 5.1 The same classification, now in the dashboard

The inspector's Memory tab listed events, conversations and thoughts; the Mind
tab showed the reflection meter, a trace of recent LLM calls, and the same
thought list again. Neither told you which thoughts were reflections — the one
kind of memory the agent produces by stepping back rather than by reacting, and
the thing the ■ markers on the stance graph point at. The two tabs are now one
**Mind** tab: the meter, then four clickable categories — Seen, Conversations,
Thoughts, Reflections — one list at a time. The LLM trace is gone from the UI
(`record_llm` still fills it and the payload still carries `llm`; see §7).

**Reflections are shown by episode, not by row,** for the reason above: a row
limit on 24 insights that all share one timestamp would show the tail of an
episode as if that were the whole of it. Each episode is one collapsed row —
`■ Mon 09:35 · 24 insights`, headlined by its most poignant insight, which is
the line the graph's tooltip already shows for the same marker — expanding to
all of them. The count on the chip is episodes; the count on Thoughts excludes
insights, so the four chips add up to what the agent actually stored.

**The classification rule is tighter than the table above.** §5 was counting
offline, where "non-empty `filling`, not a single chat" was enough. For a live
pane it has to hold for a thought whose evidence ids do not resolve at all,
which happens: `generate_insights_and_evidence` has a fallback that writes the
string `"node_1"` where a list belongs. So the rule used is **evidence that
resolves to real nodes, with no `chat` among them** — sound because insight
evidence comes from `new_retrieve`, which draws only on `seq_event` and
`seq_thought` and therefore can never cite a chat, while the two thoughts
`reflect.py` writes after a conversation cite exactly the last chat. Depth
cannot do this job: of Denise Brooks's 24 insights, 11 are depth 1 — the same
depth as a daily plan — so a `depth >= 2` test would hide them.

**Reading memory for a pane that polls every second must not change it.** This
is the §1.5 and §1.6 hazard a third time: the payload builder must not call
`new_retrieve` (it would re-stamp `last_accessed` on every poll), and it must
not sort or edit in place, because `p.a_mem.seq_thought` *is* the agent's list,
not a copy — an in-place sort would reorder the memory stream and break the
newest-first invariant `add_thought` maintains with `seq_thought[0:0] = [node]`.
Verified by loading Denise Brooks and diffing node order and every
`last_accessed` across a `_persona_state` call: both unchanged.

**The rule exists twice,** over `ConceptNode` objects in `dashboard_bridge.py`
for the live run and over `nodes.json` dicts in `translator/dashboard.py` for
saved runs, because the frontend cannot import backend modules — they reach
`utils.py` and the API keys (the same reason `_run_env` and `DEFAULT_SETTINGS`
are duplicated). Both copies agree on Denise Brooks: 177 events, 0 chats, 6
thoughts, 1 episode of 24 insights.

**Guard:** `check_memory_categories.py` runs one 12-case table through both
copies and fails if they disagree, checks `_episodes` returns distinct
timestamps newest-first, and `ast`-walks both payload builders for
`new_retrieve` and for in-place mutators on `a_mem`. It lifts the four
functions out by AST and `exec`s them rather than importing either file, since
one needs API keys and the other needs Django settings. All four rules were
proven non-vacuous by breaking the code: dropping the chat exclusion from one
copy, renaming the classifier, adding `seq_thought.sort()`, and adding a
`new_retrieve` call — each goes red with the right message.

---

## 6. How to re-verify everything

```bash
# Static guards (all of these run in CI)
.venv/bin/python scripts/ci/check_retrieval.py      # recency, weights, focal window, touch=False, one-log-per-reflection
.venv/bin/python scripts/ci/check_opinion_probe.py  # None on parse failure, read-only, no anchor list, temperature, dated evidence
.venv/bin/python scripts/ci/check_memory_categories.py  # both copies of the reflection rule agree, payload reads don't mutate
.venv/bin/python scripts/ci/check_repo.py
.venv/bin/python scripts/ci/check_dashboard_js.py

# Django
cd environment/frontend_server
../../.venv/bin/python manage.py check
../../.venv/bin/python manage.py test translator   # 13 tests

# Knowledge graph, after any code change
graphify update .
```

Expected: `0 problem(s)` from each guard, `1816 tracked files checked`,
`Dashboard script parses`, no Django issues, 13 tests OK.

The frontend was additionally verified by extracting the dashboard's inline
`<script>` and running its **real** render functions under `node` against the
real run's `opinions.jsonl` / `conversations.jsonl` / `events.jsonl`, asserting
marker counts, per-agent distribution, that every marker lies between its
bracketing readings, each tooltip body, and that markers disappear when the
source rows are removed (non-vacuity). Those harnesses live in `/tmp` and are
not checked in — they depend on a specific run's data. Re-create them from this
log if you want them back.

**Two notes on method, so you can calibrate how much to trust the above.** Most
of the guards were proven non-vacuous by deliberately breaking the code they
protect and confirming they go red: the reflection-logging guard, the earlier
probe guards, the interview `touch=False` rule (§1.6) and all four memory
category rules (§5.1). The rest are asserted-value checks against the paper's
published numbers. And the "596 reflections" figure in the first marker scoping
was wrong, which is why the reflection decision was revisited — if a number in
this log matters to a decision you are making, the commands above regenerate
it.

---

## 7. Open items

- `graphify-out/` and `.claude/` are untracked. Commit or gitignore — your call.
- README still has no dashboard run flow (`dashboard_bridge.py` usage).
- `importance_ele_n` is now write-only state; removing it touches the saved
  persona schema.
- The 300-row cap on `conversations` / `events` vs 4000 on `opinions` (§2).
- Whispers and thoughts do not decrement the reflection trigger; idle events do.
- The `llm` trace is still in the state payload but nothing renders it any more
  (§5.1). It is up to 12 entries × ~1.8 KB per persona on every poll, and only
  non-empty with `debug = True`. Drop it from `_persona_state` or give it a
  home — left in place because `record_llm` predates this change.
