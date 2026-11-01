# Memory inspection: change map

Every file touched by the interview fix and the Mind tab, what changed in it,
and which automated check covers it. For *why* any of it was done, see
[memory-inspection-engineering-log.md](memory-inspection-engineering-log.md).

`git diff --stat` is the authority on line counts; this file exists for the part
git cannot tell you — which change is load-bearing, and what proves it.
**9 files: 8 modified, 1 new.** Several of these files also carry stance-graph
changes from the same branch; the rows below describe only this work. See
[stance-graph-change-map.md](stance-graph-change-map.md) for the rest.

## Suggested review order

1. `reverie.py` — the one behavioural change. One argument, biggest effect.
2. `scripts/ci/check_memory_categories.py` + the new rule in
   `check_retrieval.py` — read the docstrings first; each states a rule and the
   bug it prevents.
3. `dashboard_bridge.py` → `translator/dashboard.py` — the same classification
   twice, live and saved. Read them side by side; that they agree is the whole
   point.
4. `translator/tests.py` — the cases that define what a reflection is.
5. `dashboard.html` — presentation only.
6. `ci.yml` — one step.

---

## Backend — agent behaviour

The only change here that alters what an agent does. Review it closest.

| File | Change | Covered by |
|---|---|---|
| `reverie/backend_server/reverie.py` | **One argument.** The `call -- interview` branch (`:773`) retrieved with the default `touch=True`, which stamped `last_accessed = now` on all 50 memories behind each answer and handed them a perfect recency score — so interviewing an agent changed what it retrieved next. Now `new_retrieve(persona, [line], 50, touch=False)` (`:793`). The comment above the branch states the invariant (nothing written, retrieval read-only, context until `end_convo`) so the next reader does not have to re-derive it. Nothing else about the feature changed: no memory was ever written, and cost was already billed through `usage.context`. | `check_retrieval.py` (`ast`: every `new_retrieve` in `open_server` passes `touch=False`) |

## Backend — the state payload

| File | Change | Covered by |
|---|---|---|
| `reverie/backend_server/dashboard_bridge.py` | `REFLECTION_EPISODES = 5` (`:158`), `_is_reflection(node, id_to_node)` (`:161`) and `_episodes(nodes)` (`:182`). `_persona_state` (`:191`) now splits `seq_thought` into plain `thoughts` and reflection `insights`, ships `reflections` (`:234`) cut on an **episode** boundary rather than a row limit, and reports `memory_counts.reflection` as a count of episodes while `thought` excludes insights — so the four categories add up to what the agent stored. **Read-only by construction:** comprehensions and slices only, no `new_retrieve`, no in-place sort. `seq_thought` is the agent's own list, not a copy, and the dashboard polls every second. | `check_memory_categories.py` (both copies agree; no `new_retrieve`; no in-place mutators) |

## Frontend

| File | Change | Covered by |
|---|---|---|
| `environment/frontend_server/translator/dashboard.py` | `_is_reflection` (`:161`), `REFLECTION_EPISODES` (`:172`) and `_episodes` (`:175`) — the same rule as `dashboard_bridge.py` but over the **dicts** in `nodes.json` rather than `ConceptNode` objects, because this module cannot import that one: it reaches `utils.py` and the API keys (the reason `_run_env` and `DEFAULT_SETTINGS` are already duplicated). `_saved_agent` (`:184`) keeps the id→node map it used to throw away, needs it to resolve `filling`, and mirrors the split and the episode cut (`:218`) so a saved run categorizes exactly as the live run does. | `manage.py test translator` (13 tests), `check_memory_categories.py` |
| `environment/frontend_server/templates/dashboard/dashboard.html` | **Presentation only** — no payload or backend contract change. (1) The `a-memory` tab button and pane are gone; **Mind** (`:435`) is now the single memory tab, rendering the next-reflection meter followed by one category at a time (`:1106-1117`). (2) New 73-line block (`:1143-1215`): `MEM_CATS`, `memCat`, `memOpen`, `memShowing`, `memCategory`, `memEpisodes`, and a delegated `click` listener on `#inspector`. Reflections render as `<details>` episodes headlined by their most poignant insight — the same line the graph's ■ tooltip shows. (3) 13 lines of CSS (`:175-187`): `.chips`/`.chip`/`details.ep`. (4) `memOpen.clear()` in the roster handler (`:1053`). **Two non-obvious choices:** the chips are `.chip[data-mem]` with a delegated listener, *not* `.tab`s, because the `.tabs` handler binds once at load and switches panes by id while the chips live inside a pane repainted every poll; and open episodes are tracked in `memOpen` rather than left to the DOM, because the meter changes the pane's HTML on every poll and `paint()` would otherwise collapse them. **Removals:** the "Latest decisions" LLM-trace section, and the two CSS rules (`details.llm .q`, `details.llm pre`) it orphaned. | `check_dashboard_js.py` (parses); the `/tmp` node harness described in the log §4 |

## Checks and config

| File | Change |
|---|---|
| `scripts/ci/check_memory_categories.py` | **New, 163 lines.** Four rules: (1) both copies of `_is_reflection` agree on a 12-case table — the shapes that actually occur, including the depth-1 event-only insight, a thought citing the last chat, unresolvable ids, and the `"node_1"` string from the fallback at `reflect.py:61`; (2) both `_episodes` return distinct timestamps, newest first; (3) neither payload builder calls `new_retrieve`; (4) neither mutates an `a_mem` sequence in place. Lifts the four functions out by AST and `exec`s them rather than importing either file — one needs API keys, the other needs Django settings — which also makes it fail loudly if a function is renamed. All four rules proven non-vacuous by breaking the code. |
| `scripts/ci/check_retrieval.py` | +1 rule (six total, 247 lines). `ast`-parses `open_server` and fails unless every `new_retrieve` inside it passes `touch=False`, **and fails if there are none at all** — so moving the interview breaks the build rather than silently dropping the protection. Reads `reverie.py` as text, since importing it reaches the API keys. |
| `environment/frontend_server/translator/tests.py` | 49 → 101 lines. `ReflectionTests`: the six cases that decide whether a thought is a reflection insight, plus `_episodes` ordering. Covers the saved-run copy of the rule; `check_memory_categories.py` is what proves the live copy matches it. |
| `.github/workflows/ci.yml` | +3 lines. `check_memory_categories.py` wired in after `check_opinion_probe.py`. It needs neither `utils.py` nor Django, but sits with the other guards. |
| `docs/stance-graph-engineering-log.md` | New §1.6 (the interview leak, as the sixth retrieval bug) and §5.1 (the dashboard's use of the reflection classification), plus updated re-verify commands and counts. **Overlaps this log** — see *Open items*. |
| `docs/stance-graph-change-map.md` | Updated rows for `reverie.py`, `dashboard_bridge.py`, `translator/dashboard.py`, `dashboard.html`, `tests.py`, `ci.yml`; new row for `check_memory_categories.py`. |

---

## What each guard would have caught

Mapping rules back to the mistakes they exist for, since a guard whose bug you
cannot name is decoration.

| Rule | The mistake |
|---|---|
| every `new_retrieve` in `open_server` passes `touch=False` | the bug that was fixed — asking an agent a question re-pins recency on 50 memories |
| …and at least one retrieval exists | moving the interview and silently losing the rule |
| both `_is_reflection` copies agree | a live run and the same run reloaded categorizing differently, with no error anywhere |
| `_episodes` returns distinct timestamps | counting one afternoon's reflection as 24 reflections |
| no `new_retrieve` in the payload builders | the interview bug again, but continuous: the dashboard polls every second |
| no in-place mutators on `a_mem` | `seq_thought.sort()` for display reordering the agent's live memory stream |
| `ReflectionTests` depth-1 case | classifying by `depth >= 2` and hiding 11 of Denise's 24 insights |

## Behaviour that did not change

Worth stating, because the point of the work was to not change it.

- **No agent writes any memory differently.** No `add_event` / `add_thought` /
  `add_chat` call site was touched.
- **No saved-state schema change.** `nodes.json` and `scratch.json` are read
  exactly as before. Every existing run loads, and reflections are inferred
  from what is already in the file.
- **No new API calls.** The Mind tab reads stored nodes; opening it costs
  nothing. The interview still costs exactly one prompt per question.
- **The state payload only grew.** `reflections` was added and
  `memory_counts.reflection` alongside the existing keys, so an older frontend
  against a newer backend degrades to ignoring them. The reverse is what
  bit in log §2.

## Open items

- The `llm` trace is still in the state payload (`_persona_state`) but nothing
  renders it since the Mind merge — up to 12 entries × ~1.8 KB per persona on
  every poll, non-empty only with `debug = True`. Left in place because
  `record_llm` predates this change. Drop it or give it a home.
- The empty state does not distinguish `reflections: undefined` (a backend
  process older than the feature) from `reflections: []` (genuinely none yet).
  Two lines; deliberately not added. Log §2.4.
- §1.6 and §5.1 of the stance-graph log now **duplicate** log §1 and §3 here.
  Two copies of a rationale drift apart — the failure these documents exist to
  prevent. Either trim those two sections to a pointer, or keep this pair as
  the single source and leave them as the branch's summary. Not decided.
- A reflection is identified by inference rather than by a flag at write time.
  A `kind` field in `add_thought` would make both copies of the classifier
  unnecessary, but it touches the saved persona schema.

## Verified at

`stg-base_the_ville_datacenter_n8-3`. All guards `0 problem(s)`,
`1816 tracked files checked`, 13 Django tests OK, `Dashboard script parses`,
`graphify update .` clean. Live and saved payload builders agree on Maya
Okonkwo (`{event: 130, chat: 2, thought: 10, reflection: 1}`, 14 insights) and
Denise Brooks (`{event: 177, chat: 0, thought: 6, reflection: 1}`, 24
insights). `_persona_state` leaves node order and every `last_accessed`
unchanged, checked by diffing before and after.
