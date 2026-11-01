# Memory inspection: engineering log

Why the dashboard's two windows into an agent's memory — the **Interview** and
the **Mind** tab — work the way they do. Two bugs and one feature, in the order
they were found.

For *which files changed and why*, see
[memory-inspection-change-map.md](memory-inspection-change-map.md). The
stance-graph pair ([engineering log](stance-graph-engineering-log.md),
[change map](stance-graph-change-map.md)) covers the probe and the graph; the
retrieval groundwork both of these rest on is §1 of that log.

**The one rule behind all three items:** an observer looking at an agent must
not change the agent. The dashboard is a microscope, and a microscope that
heats the sample is measuring itself.

---

## 0. What was built

| | |
|---|---|
| **Bug 1** | The interview stamped `last_accessed` on every memory behind an answer, so asking an agent a question changed what it retrieved next. Fixed with `touch=False`; guarded by `check_retrieval.py`. |
| **Bug 2** | The Mind tab reported "No reflections yet" for an agent the stance graph showed as having reflected. Not a code defect — a live backend process running pre-change code. Diagnosed, not patched. |
| **Feature** | The inspector's Mind and Memory tabs merged into one **Mind** tab: the next-reflection meter plus four clickable categories — Seen, Conversations, Thoughts, Reflections — with reflections grouped into episodes. Guarded by `check_memory_categories.py` (163 lines, 4 rules) and `ReflectionTests`. |

---

## 1. Bug 1: the interview changed the memory it read

### 1.1 What the feature does

`call -- interview <Agent> ;; <question>` (`reverie.py:773`) answers as the
agent, from the agent's own memories. The question is retrieved against, the
hits become the context for a prompt, and the answer comes back to the
dashboard's Interview pane. Earlier turns of the same interview stay as context
in `self._interviews` (`reverie.py:597`) until `end_convo`.

The design intent was already right in two of three respects:

- **Nothing is written.** No `add_event`, no `add_thought`, no `add_chat`. The
  interview transcript lives in `self._interviews`, a plain dict on the server
  object that is never serialized into the save.
- **Cost is attributed.** The prompt bills through `usage.context`, so
  interview spend is separable from simulation spend.

### 1.2 What leaked

The retrieval itself. `new_retrieve(persona, [line], 50)` ran with the default
`touch=True`, and `touch=True` stamps `last_accessed = now` on everything it
returned (`retrieve.py:276`).

`last_accessed` is the input to `extract_recency`, which scores
`recency_decay ** hours_since_last_accessed`. Stamping it sets that term to
**1.0 — a perfect recency score** — for all 50 nodes. So:

> Ask Elena Chen what she thinks of the datacenter, and the 50 memories behind
> her answer become, as far as the agent is concerned, the 50 things she most
> recently thought about. Her next perception, her next conversation, her next
> reflection all retrieve against a memory stream the question reshaped.

This is the same defect as the one already fixed in the stance probe
(stance-graph log §1.5), arriving through a different door: the probe is an
instrument we wrote and remembered to make read-only; the interview is a
*feature* that happens to retrieve.

The user's framing was the correct one: *"if the interview is changing the
last_accessed, then it's indirectly touching and changing agent's memory."*
Nothing is added — but what the agent will retrieve next is different, and
that is the part that matters.

### 1.3 How bad it was

Bounded, and the bound is worth knowing because it explains why nobody noticed.

`last_accessed` is **not serialized**. `nodes.json` has no such field;
`AssociativeMemory.__init__` sets `last_accessed = created` on load. So the
perturbation lives only in the running process and dies when it exits — it
corrupts the *rest of the current session*, not the saved run.

That is small comfort during a long run, which is exactly when interviewing is
most interesting.

### 1.4 The fix

One argument:

```python
retrieved = new_retrieve(persona, [line], 50, touch=False)[line]   # reverie.py:793
```

`touch=False` was already there — added for the stance probe (stance-graph log
§1.5), which needed the same property. The interview just never used it. The
comment above the branch now states the invariant so the next reader does not
have to re-derive it.

### 1.5 Guard

A sixth rule in `check_retrieval.py`: `ast`-parse `open_server`, find every
`new_retrieve` call inside it, and fail unless each passes `touch=False`.

Two deliberate choices:

- **It also fails if there are no retrievals at all**, so moving the interview
  elsewhere breaks the build rather than silently removing the protection.
- **`reverie.py` is read as text, not imported**, because importing it reaches
  `utils.py` and the API keys. Same reason the frontend duplicates `_run_env`.

Proven non-vacuous by reverting the fix and watching CI name line 793.

---

## 2. Bug 2: "No reflections yet" for an agent that had reflected

Reported right after the feature shipped: the stance graph showed a ■
reflection marker for Maya Okonkwo in `stg-base_the_ville_datacenter_n8-3`,
while her Mind tab said no reflections yet.

**It was not a code defect, and the data was fine.** Worth recording because
the architecture makes this reachable again.

### 2.1 The evidence

Maya's saved `nodes.json`: 130 events, 2 chats, 24 thoughts — of which **14 are
insights, all at `2023-02-13 10:37:30`**, evidence of events and thoughts, no
chats. The exact timestamp of her graph marker. Running `_saved_agent` on her
returned `{event: 130, chat: 2, thought: 10, reflection: 1}` with 14 insights
shipped. Both the data and the new code were correct.

The payload the browser was actually reading was not.

```
reverie.py backend pid 72382   started 17:27
temp_storage/dashboard/state.json   written 18:13
dashboard_bridge.py edited          ~19:05
```

`state.json` had **no `reflections` key at all** and
`memory_counts: {event: 130, thought: 24, chat: 2}` — the old shape, with
insights still inside `thought`.

### 2.2 Why

Three facts compose into it:

1. The reverie backend and the Django frontend are **separate processes** that
   talk through files in `temp_storage/dashboard/`. The backend imported
   `dashboard_bridge` at 17:27 and Python does not reload modules, so it kept
   writing the old payload shape for the rest of its life.
2. The ■ marker reads `experiment/events.jsonl` **on disk**, which was written
   during the run and was current. So the marker was right and the pane was
   stale — from two different sources.
3. Re-opening the run in the browser could not help. `dashboard.html:1345`
   treats a selected run as a *saved* view only if it is not the sim the live
   backend holds; here they were the same name, so the dashboard read
   `state.json` and never touched the saved `nodes.json` that had the answer.

Confirmed by rendering the stale payload through the template's real JS:

```
chips: Seen 130 | Conversations 2 | Thoughts 24 | Reflections 0
reflection pane: "No reflections yet. ..."
```

An exact match for the reported screen. **`Thoughts 24` is the tell** — under
the new code those 24 split into 10 thoughts and 14 insights.

### 2.3 Resolution

Stop the backend (the save was already current: `meta.json` step 4000 = live
step 4000, same `curr_time`, so nothing was unflushed). Once pid 72382 exits,
`_backend_status` reports `stopped`, the dashboard switches to `_saved_agent`,
and Maya shows `■ Mon 10:37 · 14 insights`. Confirmed working.

### 2.4 Not fixed, on purpose

The frontend *can* tell `reflections: undefined` (backend predates the feature)
from `reflections: []` (genuinely none yet), and could say so instead of making
a claim that is wrong. Two lines. Left out: it is scaffolding for a transient
condition, and a version handshake between the two processes is a feature
nobody asked for. Recorded here so the next person who hits it spends five
minutes instead of an hour. See change map, *Open items*.

**The general lesson:** in this architecture, a code change does not take
effect until the backend process restarts. Anything read from `state.json` is
as old as the process; anything read from `storage/` is as old as the last save.
When those two disagree on screen, suspect the process before the code.

---

## 3. Feature: the Mind tab

### 3.1 What was wrong with the old panes

The inspector had two memory tabs. **Memory** listed events, conversations and
thoughts; **Mind** showed the reflection meter, a trace of recent LLM calls, and
*the same thought list again*. Neither told you which thoughts were
reflections — the one kind of memory an agent produces by stepping back rather
than by reacting, and the thing the graph's ■ markers point at.

The requirement, in the user's words: *"I want the display to be categorized
into event, chat, thought and reflection. So, I can click on one and know what
I'm looking at"* — then *"combine the Mind and Memory, and title it as Mind"*,
keeping the next-reflection meter and nothing else, and *"by reflection I mean
the episodes, the way the graph implements it."*

### 3.2 Four categories, three of them easy

`event`, `chat` and `thought` are literally `node.type`, maintained as three
parallel lists (`seq_event`, `seq_chat`, `seq_thought`). Reflection is not a
type. It is a *subset of* `thought`, and **nothing marks it at write time.**

### 3.3 Why depth cannot identify a reflection

The obvious candidate, and it is wrong. `add_thought` sets
`depth = 1 + max(depth of its evidence)` when the evidence resolves. An insight
drawn entirely from events therefore has depth 1 — identical to a daily plan
(`plan.py`) or a whisper (`converse.py`).

Measured, not assumed: of Denise Brooks's 24 insights, **11 are depth 1 and 13
are depth 2.** A `depth >= 2` test would have hidden eleven of her twenty-four.

### 3.4 The rule that works, and why it is sound

> A thought is a reflection insight iff its `filling` resolves to real nodes
> and **none of them is a `chat`**.

It is sound because of where each kind of evidence comes from:

- **Insight evidence** comes from `new_retrieve`, which draws only on
  `seq_event` and `seq_thought`. It is structurally incapable of citing a chat.
- **The two thoughts `reflect.py` writes after a conversation** — the planning
  thought and the memo thought — share one `evidence` list built at
  `reflect.py:237` as `[get_last_chat(...).node_id]`. Exactly the last chat,
  and nothing else.
- **Plans, whispers and seed identity thoughts** carry no resolvable evidence
  at all.

So the presence of a chat rules a reflection out, and resolvable evidence rules
the non-reflections out.

The "resolves" half matters more than it looks:
`generate_insights_and_evidence` has a bare `except` whose fallback returns
`{"this is blank": "node_1"}` (`reflect.py:61`) — the **string** `"node_1"`
where a list belongs. The stance-graph log §5 classified reflections
offline as "non-empty `filling`, not a single chat", which was fine for
counting but would call that degenerate row a reflection. The live rule is
stricter on purpose; both shapes are in the guard's fixture table.

Validated against real saved data before shipping — Denise Brooks's 24 insights
classified correctly, Aisha Rahman's 2 post-conversation thoughts correctly
excluded, Maya Okonkwo's 14 insights found and her 4 chat-cited thoughts not.

### 3.5 Episodes, not rows

One `run_reflect` call writes up to ~15 insights **all at one timestamp** and
logs one `events.jsonl` row — that row is the ■ marker (stance-graph log §4).
So "reflection" as the user means it is the *episode*, not the insight.

Consequences, both load-bearing:

- **The count is episodes.** Denise's chip reads 1, not 24. Counting rows would
  report one afternoon's reflection as twenty-four reflections.
- **The cut is on an episode boundary.** `REFLECTION_EPISODES = 5` limits
  *timestamps*, then every insight at those timestamps ships. A row limit of 15
  against a 24-insight episode would show the tail of an episode as if that
  were the whole of it.

Each episode renders as one collapsed row —
`■ Mon 09:35 · 24 insights` — headlined by its **most poignant** insight,
which is the same line the graph's tooltip already shows for that marker, so
the two views of one event agree. Expanding gives all of them.

The `thought` count excludes insights, so the four chips add up to what the
agent actually stored.

### 3.6 Meter vs episode — the same counter from both ends

Asked directly, and worth writing down. `perceive.py:178` subtracts each new
event's poignancy from `importance_trigger_curr`; `reflect.py:175` fires when
it reaches `<= 0`; `reset_reflection_counter` restores it.

- The **meter** is the fuse: ephemeral `scratch` state, a countdown, no history.
- An **episode** is the bang: durable nodes plus one `events.jsonl` row.

Same mechanism, opposite ends — which is why the merged tab shows the meter
above the list. The meter is what is about to happen; the episodes are what
already did.

### 3.7 Reading memory for display must not change it

The user's constraint, stated before implementation: *"By accessing details
from insight nodes, there's no change in the agent memory, right? Like last
accessed, or etc... Cause that would create a wrong logic."*

Correct, and twice as important here as in the interview, because **the
dashboard polls every second.** A `new_retrieve` in the payload builder would
not perturb memory once, it would re-pin a recency score of 1.0 continuously.

Verified by audit, then by experiment:

- `last_accessed` is written in exactly three places repo-wide; only
  `retrieve.py:276` is live code, and it is inside `if touch:`.
- No `@property`, `__getattr__` or `__getattribute__` anywhere in
  `memory_structures/`, so attribute reads cannot have side effects.
- `_persona_state` uses only `len()`, slices and comprehensions.
- **Loaded Denise Brooks, snapshotted node order and every `last_accessed`,
  called `_persona_state`, diffed: both unchanged.**

One adjacent hazard the user had not asked about, found while checking:
`p.a_mem.seq_thought` **is the agent's list, not a copy.** An in-place
`.sort()` for display would reorder the live memory stream and break the
newest-first invariant `add_thought` maintains with `seq_thought[0:0] = [node]`.
Hence: `sorted()`, comprehensions and slices only — and a guard rule for it.

### 3.8 The rule exists twice, on purpose

Once over `ConceptNode` objects (`dashboard_bridge.py`, live run) and once over
`nodes.json` dicts (`translator/dashboard.py`, saved runs). The frontend cannot
import the backend: it reaches `utils.py` and the API keys. `_run_env` and
`DEFAULT_SETTINGS` are duplicated for the same reason.

Duplication of a *rule* is worse than duplication of a constant, because the
copies can drift apart silently and categorize the same run two different ways.
So the guard's first job is to prove they agree.

Both copies on Maya Okonkwo: `{event: 130, chat: 2, thought: 10, reflection: 1}`,
14 insights shipped. Both on Denise Brooks:
`{event: 177, chat: 0, thought: 6, reflection: 1}`, 24 insights shipped.

### 3.9 Two UI details worth knowing

- **The chips are not `.tab`s.** The `.tabs` handler binds once at load and
  switches panes by element id; the chips live *inside* a pane that is
  repainted on every poll. They use `.chip[data-mem]` and a delegated listener
  on `#inspector`.
- **Open episodes are tracked in state, not in the DOM.** `paint()` skips a
  repaint when the HTML is byte-identical, which is why the old conversation
  `<details>` stayed open. The meter moves on every poll, so the Mind pane's
  HTML now changes constantly — without the `memOpen` set, an episode you
  opened would shut itself a second later. It is cleared when you switch
  agents, since timestamps belong to the agent they came from.

### 3.10 Guard

`check_memory_categories.py`, four rules:

1. Both copies of `_is_reflection` agree on a **12-case table** — event-only
   evidence (the depth-1 case), thought evidence, chat evidence, mixed
   event+chat, empty list, unresolvable ids, `None`, the `"node_1"` string, and
   non-thought types.
2. Both `_episodes` return distinct timestamps, newest first.
3. Neither payload builder calls `new_retrieve`.
4. Neither mutates an `a_mem` sequence in place (`sort`, `reverse`, `append`,
   `pop`, `insert`, `remove`, `clear`, `extend`).

It **lifts the four functions out by AST and `exec`s them** rather than
importing either file — one needs API keys, the other needs Django settings.
That also makes it fail loudly if a function is renamed, instead of quietly
checking nothing.

All four proven non-vacuous by breaking the code and watching it go red:
dropping the chat exclusion from one copy (2 problems, the right 2), renaming
the classifier (names the file and the consequence), adding
`seq_thought.sort()`, and adding a `new_retrieve` call. Repo restored after
each.

---

## 4. How to re-verify everything

```bash
# Static guards (all of these run in CI)
.venv/bin/python scripts/ci/check_retrieval.py          # incl. every new_retrieve in open_server passes touch=False
.venv/bin/python scripts/ci/check_memory_categories.py  # both copies agree; payload reads don't mutate
.venv/bin/python scripts/ci/check_repo.py
.venv/bin/python scripts/ci/check_dashboard_js.py

# Django
cd environment/frontend_server
../../.venv/bin/python manage.py check
../../.venv/bin/python manage.py test translator        # 13 tests

# Knowledge graph, after any code change
graphify update .
```

Expected: `0 problem(s)` from each guard, `1816 tracked files checked`,
`Dashboard script parses`, no Django issues, 13 tests OK.

**End-to-end, without spending anything on the API:** load
`stg-base_the_ville_datacenter_n8-3` and open the Mind tab for Denise Brooks
(177 / 0 / 6 / 1 episode of 24) or Maya Okonkwo (130 / 2 / 10 / 1 episode of
14). Every category non-empty across the two. Four agents reflected in that
run — Denise 24 insights at 09:35, Tom 11 at 10:04, Marcus 20 at 10:31, Maya
14 at 10:37 — so the chip count should match the ■ markers on the graph.

**If the Mind tab disagrees with the graph, read §2 before reading the code.**

The Mind pane was additionally verified by extracting the template's `<script>`
and running its **real** `memCategory` / `memEpisodes` against real payloads
under `node`: all four categories, balanced tags, the truncation hint
(`Showing the 15 most recent of 177.`) appearing only where the list is
actually cut, and the episode expanding to exactly 24 `<li>`. That harness
lives in `/tmp` and is not checked in — it depends on a specific run's data.
Re-create it from this log if you want it back.

**On method.** Every guard rule described above was proven non-vacuous by
deliberately breaking the code it protects. The counts are measured off
`stg-base_the_ville_datacenter_n8-3`, not estimated; if a number here matters
to a decision you are making, the commands above regenerate it.

---

## 5. Open items

- The `llm` trace is still in the state payload but nothing renders it since
  the Mind merge — up to 12 entries × ~1.8 KB per persona on every poll, and
  only non-empty with `debug = True`. Drop it from `_persona_state` or give it
  a home.
- `reflections: undefined` vs `[]` is not distinguished in the empty state
  (§2.4).
- `REFLECTION_EPISODES = 5` and the 15-row cap on events/thoughts are
  hard-coded. Fine today; they are what "showing X of Y" exists to admit.
- A reflection is identified by inference, not by a flag. A `kind` field set at
  write time in `add_thought` would make both copies of the rule unnecessary —
  but it touches the saved persona schema, so every existing run would need a
  migration or a fallback to exactly this rule.
