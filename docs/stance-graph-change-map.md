# Stance graph: change map

Every file touched, what changed in it, and which automated check covers it.
For *why* any of it was done, see
[stance-graph-engineering-log.md](stance-graph-engineering-log.md).

The interview fix and the Mind tab have their own pair:
[memory-inspection-change-map.md](memory-inspection-change-map.md) and
[memory-inspection-engineering-log.md](memory-inspection-engineering-log.md).
Rows below that mention them are summaries; those two are the full record.

`git diff --stat` is the authority on line counts; this file exists for the
part git cannot tell you — which change is load-bearing, and what proves it.
19 files: 14 modified, 5 new.

## Suggested review order

1. `retrieve.py` — the behavioural change. Everything else builds on it.
2. `scripts/ci/check_retrieval.py` + `check_opinion_probe.py` — read the
   docstrings first; they state each rule and the bug it replaced.
3. `opinion_probe.py` → `run_gpt_prompt.py` → `datacenter_stance_v1.txt` — the
   measurement path, in call order.
4. `reverie.py` → `experiment_logger.py` → `translator/dashboard.py` — how a
   reading reaches the browser.
5. `dashboard.html` — presentation only.
6. `reflect.py` — two unrelated changes; see the note below.

---

## Backend — agent behaviour

These are the only changes that alter what the agents do. Review them closest.

| File | Change | Covered by |
|---|---|---|
| `reverie/backend_server/persona/cognitive_modules/retrieve.py` | `extract_recency` now decays over game hours since `last_accessed` instead of over list position (it previously ranked the oldest memory as the most recent). Retrieval weights `gw` set to `[1, 1, 1]`. New `touch=True` parameter on `new_retrieve`: `False` returns nodes without stamping `last_accessed`, which is what lets an observer read memory without perturbing it. | `check_retrieval.py` (exact decay values, ranking, order-independence, weights, both sides of `touch`) |
| `reverie/backend_server/persona/cognitive_modules/reflect.py` | **Two unrelated changes.** (a) `generate_focal_points` sorts by `created` (was `last_accessed`) and windows on the new `FOCAL_POINT_RECORDS = 100` instead of `importance_ele_n`, a counter that did not match the list it indexed and that sliced in the *whole* memory stream whenever it was 0. (b) `run_reflect` collects its insights and logs **one** `event_type="reflection"` row per episode, after both loops — the source of the ■ markers. | `check_retrieval.py` (focal window contents; `ast` check that the log call exists and is not inside a loop) |
| `reverie/backend_server/persona/memory_structures/scratch.py` | `recency_decay` default `0.99` → `0.995`, the paper's value. **One line, and it affects nothing in practice:** a saved persona's `bootstrap_memory/scratch.json` overrides it, and every seed in this repo already carried `0.995`. | — |

## Backend — the stance probe (new path, no agent state touched)

| File | Change | Covered by |
|---|---|---|
| `reverie/backend_server/opinion_probe.py` | **New, 41 lines.** `probe(persona)` → `(score, rationale, evidence)`. Retrieves 30 nodes against a fixed question with `touch=False`, re-sorts them oldest-first, and dates each line before handing them to the prompt. | `check_opinion_probe.py` |
| `reverie/backend_server/persona/prompt_template/v3_ChatGPT/datacenter_stance_v1.txt` | **New, 22 lines.** The 1–100 rating prompt. Deliberately offers **no list of anchor values** — with anchors, `gpt-4o-mini` used only 6 distinct values across 192 readings. Tells the model to rate the position held at the *end* of the memories, not their average. | `check_opinion_probe.py` (fails if an anchor list reappears) |
| `reverie/backend_server/persona/prompt_template/run_gpt_prompt.py` | +91 lines, all appended. `STANCE_QUESTION`, `STANCE_SCALE = 100`, `STANCE_SEPARATOR`, `parse_stance()` (returns `None`, never a fallback number, so a failed read is a gap rather than a fabricated opinion), and `run_gpt_prompt_datacenter_stance()`. The only prompt in the codebase that passes `temperature` through to the API. | `check_opinion_probe.py` (parse failures → `None`, temperature is passed) |
| `reverie/backend_server/persona/prompt_template/gpt_structure.py` | `ChatGPT_request` and `ChatGPT_safe_generate_response` take an optional `temperature`. `None` leaves the existing default in place, so **no existing caller changes behaviour**. | Django `test translator` + every other prompt still running |
| `reverie/backend_server/reverie.py` | +49 lines. New `probe_opinions()` method: skips agents with no clock, tags `usage.context` with `source="opinion_probe"` so measurement cost is billed separately from steps, records `scale`/`model`/`run_env` on every row. Called from the step loop when `step % opinion_steps == 0`. New console command `call -- probe now` for an unscheduled read. The `call -- interview` command retrieves with `touch=False`: it writes no memory, and now does not stamp `last_accessed` on the 50 memories behind an answer either. | `check_retrieval.py` (`ast` check that every `new_retrieve` in `open_server` passes `touch=False`) |
| `reverie/backend_server/experiment_logger.py` | +13 lines. `log_opinions()` writes one row per agent per probe to `experiment/opinions.jsonl`. A `None` score is written as `null` and kept as a gap. | — |
| `reverie/backend_server/dashboard_bridge.py` | `opinion_steps: 360` added to `DEFAULT_SETTINGS` (360 steps = 1 game hour, `0` = off), so the interval is live-editable mid-run like `autosave_steps`. Plus `_is_reflection` / `_episodes` and a `reflections` list in the state payload, which split reflection insights out of `thoughts` for the Mind tab. Read-only by construction: comprehensions and slices, no `new_retrieve`, no in-place sort — `seq_thought` is the agent's own list. | `check_memory_categories.py` |

## Frontend

| File | Change | Covered by |
|---|---|---|
| `environment/frontend_server/translator/dashboard.py` | New `_opinions()` helper feeds 4000 rows into both payloads (`dashboard_run` and `dashboard_state`) and **strips the `evidence` node ids** — they stay in the file for analysis but are not shipped to the browser on every poll. `opinion_steps` added to `DEFAULT_SETTINGS` and validated in `dashboard_settings` (whole number, 0–100000). Separately, `_saved_agent` gained the same `_is_reflection` / `_episodes` split as `dashboard_bridge.py` over `nodes.json` dicts, so a saved run categorizes the same way the live run does. | `manage.py test translator` (13 tests), `check_memory_categories.py` |
| `environment/frontend_server/templates/dashboard/dashboard.html` | +362 lines, **presentation only** — no payload or backend contract changes. Three groups: (1) the stance graph itself — `renderStance`, `STANCE_COLORS`, SVG geometry constants, time-axis tick formatting that widens from hours to days, per-row `scale` handling so 1–10 history renders correctly next to 1–100, custom zero-delay tooltip, selection-scoped hit-testing via `stanceNearest`; (2) event markers — `STANCE_EVENT_MARKS` shape registry, interpolated placement, `stanceClick`, `convoKey`/`openConvo`/`showConvo` for click-through to a transcript that survives repaints, `.convo.flash`; (3) a `opinion_steps` field in the settings dialog. `renderEvents` gained one filter so reflections stay out of the Whispers pane. Separately, the inspector's **Mind and Memory tabs are now one Mind tab**: the reflection meter plus four `.chip` categories (`MEM_CATS`, `memCategory`, `memEpisodes`, `memOpen`) showing one list at a time, reflections grouped into `<details>` episodes headlined by their most poignant insight. Chips use a delegated listener on `#inspector` rather than the `.tabs` handler, which binds once at load and switches panes by id. The "Latest decisions" LLM trace was dropped. | `check_dashboard_js.py` (parses); the `/tmp` node harnesses described in the log |

## Checks and config

| File | Change |
|---|---|
| `scripts/ci/check_retrieval.py` | **New, 247 lines.** Six rules: recency decays over elapsed time and ranks freshest-first; recency is order-independent; weights are `[1,1,1]`; the focal-point window is the 100 most recently created non-idle records; `touch=False` preserves `last_accessed` while the default still stamps it; every `new_retrieve` in `open_server` passes `touch=False`, so no console command perturbs what it read (`ast`-based, and fails if no command retrieves at all); a reflection is logged once, not per insight (`ast`-based). The docstring names the bug behind each rule. |
| `scripts/ci/check_opinion_probe.py` | **New, 135 lines.** Five rules: a response with no valid number scores `None`; the probe retrieves read-only; the prompt hands the model no anchor list; temperature is passed explicitly; evidence reaches the model oldest-first and dated. |
| `scripts/ci/check_memory_categories.py` | **New, 163 lines.** Four rules: the live and saved copies of `_is_reflection` agree on a 12-case table (the fixtures that actually occur — event-only evidence, chat evidence, unresolvable ids, the `filling="node_1"` string from the insight prompt's fallback); `_episodes` returns distinct timestamps newest-first in both; neither payload builder calls `new_retrieve`; neither mutates an `a_mem` sequence in place. Lifts the four functions out by AST and `exec`s them, because one file needs API keys and the other needs Django settings. |
| `environment/frontend_server/translator/tests.py` | +50 lines. `ReflectionTests`: the six cases that decide whether a thought is a reflection insight, plus `_episodes`. Covers the saved-run copy of the rule; `check_memory_categories.py` is what proves the live copy matches it. |
| `.github/workflows/ci.yml` | +10 lines. All three new checks wired in after the step that writes `utils.py` (the first two import the backend, so they need it). |
| `CLAUDE.md` | +12 lines (graphify usage rules). Unrelated to this feature. |
| `.gitattributes` | +1 line: `graphify-out/graph.json merge=graphify`. Unrelated to this feature. |

## Not committed

`graphify-out/` (regenerable: `graphify update .`) and `.claude/` are untracked.
Decide whether to commit or gitignore them before this branch merges.

## Data this produces

`storage/<sim>/experiment/opinions.jsonl` — one row per agent per probe:

```json
{"step": 360, "time": "February 13, 2023, 01:00:00", "name": "Maya Okonkwo",
 "score": 10, "scale": 10, "rationale": "I firmly believe the datacenter will
 create high-skill jobs...", "evidence": ["node_123", "..."],
 "model": "gpt-4o-mini", "run_env": "stg"}
```

`score: null` means the model gave no usable rating — a gap in the line, not a
zero. `scale` is per-row because it has already changed once (10 → 100), and
old rows must keep rendering on the scale they were taken on.
