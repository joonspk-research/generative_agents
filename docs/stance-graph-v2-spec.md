# Datacenter Town — Stance Graph 2.0 Implementation Specification

**Reference repository:** `mitsvision2/datacenter-town`  
**Reference branch:** `mhdgohel-datacenter-town`  
**Reviewed reference commit:** `8562d994cd18a7fc7d5c7f87789b87c6d22edd9b`  
**Status:** Requirements approved for implementation; this document is a specification, not code.

## 1. Goal and non-negotiable decisions

Implement two features on the existing Datacenter Town dashboard:

1. **Rubric-based stance scoring:** Keep the existing evidence retrieval and use the LLM to determine the agent's stance category and choose an integer score within that category's **0–100** range. The graph continues to show one line per agent over time.
2. **Live social interaction network:** Add a panel with one labeled circle per agent, colored according to their latest *valid* stance. Create undirected edges when completed agent-to-agent conversations are recorded; retain one cumulative edge per pair, with thickness increasing with conversation count.

User-confirmed choices:

- **Scoring:** LLM selects the specific score within a rubric band. Do not force a fixed category midpoint and do not sum questionnaire answers.
- **Interactions:** Only completed, logged conversations create edges; not mere proximity, thoughts, reflections, or whispers.
- **Edges:** Cumulative; repeated conversations increase a single existing edge's count and thickness.
- **Missing stance:** Retain each agent's most recent **valid** score/color; gray only if they have never been rated successfully.
- **Placement:** New panel below/alongside the existing stance line graph in the dashboard; do not replace the line graph. Prefer below it to avoid compressing the existing layout.

**Do not modify the agent simulation's cognitive behavior, decisions, memory-writing, planning, or conversation generation.** Measurement remains read-only. Do not add a persuasion model or assert that conversation connections establish causal influence.

## 2. Reference implementation — inspect before editing

The reviewed code already has:

- `reverie/backend_server/opinion_probe.py`: selects relevance-filtered events/thoughts and up to ten of an agent's own quoted utterances, combines evidence chronologically, and invokes stance evaluation read-only.
- `reverie/backend_server/persona/prompt_template/run_gpt_prompt.py`: `STANCE_SCALE=100`, `parse_stance`, `run_gpt_prompt_datacenter_stance`, and prompt validation. **Currently accepts 1–100, not 0–100.**
- `reverie/backend_server/persona/prompt_template/v3_ChatGPT/datacenter_stance_v2.txt`: current direct 1–100 scoring prompt.
- `reverie/backend_server/reverie.py`: periodic `probe_opinions()` with the experiment logger.
- `reverie/backend_server/experiment_logger.py`: writes `opinions.jsonl` and `conversations.jsonl` under `storage/<sim>/experiment/`.
- `environment/frontend_server/translator/dashboard.py`: provides live and saved-run JSON, including stance rows and a tail of **300 conversations**; this tail is **not adequate** for cumulative conversation counts.
- `environment/frontend_server/templates/dashboard/dashboard.html`: existing stance SVG line chart, activity/history panes, roster, and ~1-second state polling.
- `scripts/ci/check_opinion_probe.py` and related test scripts: existing probe checks.

Before implementation, verify paths and current code rather than assuming every reference remains accurate. Verify the checkout's HEAD relative to the reviewed commit; if newer code conflicts with this spec, describe the difference rather than silently overwriting it.

## 3. Feature A — Rubric-based numerical stance scoring

### 3.1 Scoring target

Evaluate **the agent's current support or opposition to approving the specific data-center proposal in its current form**, as of the simulation's current time. Do not confuse support for data centers generally with support for this proposal, and do not confuse participation in research/planning with approval.

### 3.2 Exact bands

| Integer score | Classification | Canonical ID |
|---|---|---|
| 0–19 | Very strong opposition | `very_strong_opposition` |
| 20–39 | Moderate opposition | `moderate_opposition` |
| 40–49 | Slight opposition | `slight_opposition` |
| 50 | Neutral / genuinely mixed | `neutral_mixed` |
| 51–60 | Slight support | `slight_support` |
| 61–80 | Moderate support | `moderate_support` |
| 81–100 | Very strong support | `very_strong_support` |

Ranges include both endpoints. **0 and 100 are valid.** `50` means genuine neutrality/ambivalence supported by the evidence, not absence of evidence. Unavailable or invalid measurements are `null`.

### 3.3 Evaluation behavior

Keep the current retrieval, unless a small compatibility adjustment is strictly required. The probe currently reserves up to 10 direct utterance slots within an evidence budget of up to 30, deduplicates canonical memory statements, applies a similarity floor of 0.45 to retrieved event/thought memory, and withholds for sleep/low relevance. Preserve existing observer-read-only protections (`touch=False`, don't insert probe embeddings into persisted agent memories).

The updated scorer should:

1. Read the evidence with chronological context and attribution to the correct speaker.
2. Identify the best-supported stance **category** before determining a number.
3. Choose an **integer 0–100 within the selected band's exact range**, using the expressed strength of the stance to distinguish values. Do not automatically choose category midpoints or default to multiples of 5/10.
4. Produce a short rationale. If supported by evidence, identify conditions affecting the stance (e.g., an enforceable local hiring guarantee).
5. Abstain (`null`) when the record cannot justify a judgment. A genuinely neutral opinion may be scored `50` when supported by evidence; an unknown opinion must not silently be scored `50`.
6. Base the score on the *end* of the available record, not the average of all historical statements; be attentive to explicit later reversals and conditions.
7. Avoid attributing another person's quoted stance to the agent under evaluation; direct speech from this agent is stronger attribution evidence than generic conversation summaries.

Prefer machine-parseable structured output for `category`, `score`, `rationale`, and optionally `conditions`; preserve existing consumers or migrate them safely. Keep the evaluation to approximately the same number of LLM calls per scheduled probe, rather than adding an agent interview or separate LLM call for each sub-question.

### 3.4 Validation and persisted record

Backend validation must ensure:

- Score is an integer within 0–100.
- Chosen category exactly matches its score band.
- Invalid/inconsistent outputs are retried within the existing bounded-retry policy and otherwise recorded as `null`, not silently coerced into a different category.
- The explicit abstention pathway remains valid.
- Relevance, `withheld`, and quoted-span metadata are retained.

Prefer preserving existing logger schema fields and extending `opinions.jsonl` readings with:

- `category`: canonical classification identifier for a valid reading, else `null`.
- `conditions`: optional list of explicitly supported conditions; no invented guarantees.
- `scoring_version`: e.g. `rubric_v1`, to separate new measurements from legacy direct 1–100 scoring.

Also preserve `step`, `time`, `name`, `score`, `scale`, `rationale`, `evidence`, `relevance`, `withheld`, `quoted`, `model`, and existing environment context as applicable. Persist no new agent beliefs to agent memory.

### 3.5 Existing line graph and backward compatibility

- Change the **new scale's** vertical coordinate domain to 0–100 (0 at bottom, 100 at top); display clear axis labels.
- Retain separate lines per agent, current conversation/whisper/reflection markers, rationale hover, settings-controlled probe interval, and gaps for null readings.
- Existing `STANCE_COLORS` in the line chart are agent identity colors and can remain unchanged. New network node colors will encode stance strength instead.
- Preserve readability of old runs. Old scoring was 1–100 with `scale=100`, so `scoring_version` (missing on old rows) must be considered when mapping and interpreting legacy points. Do not silently rewrite historical scores, categories, or scales.
- A run mixing different scoring methods should identify that the readings are not directly comparable without calibration.

## 4. Feature B — Live social interaction network panel

### 4.1 Basic appearance

Place a clearly titled **Social Interaction Network** panel adjacent to or below the current line graph (default below), integrated with existing dashboard styling, responsive layout, and dark mode.

- Nodes: one circular node for every name in the simulation persona roster, visible as soon as the simulation loads—even before a probe or conversation.
- Labels: visible character names; use legible positioning and/or short display labels with full name in tooltip.
- Positions: stable per simulation (deterministic layout), and not reordered whenever a conversation occurs.
- No edges initially for a new run with no conversations.
- Before first valid score, node is gray. Forked runs may begin with inherited colors/edges from inherited records.

### 4.2 Node stance mapping

| Category | Color |
|---|---|
| Very strong opposition (0–19) | `#A32834` dark red |
| Moderate opposition (20–39) | `#DD645D` red |
| Slight opposition (40–49) | `#EFAA86` orange |
| Neutral/mixed (50) | `#D5B55C` yellow |
| Slight support (51–60) | `#A0CAA0` light green |
| Moderate support (61–80) | `#48A276` green |
| Very strong support (81–100) | `#17754E` dark green |
| Unrated | `#9299A4` gray |

Derive the color from the **latest valid** recorded stance score at or before the currently viewed run step. If the newest reading is null (asleep, low relevance, failed evaluator), retain the preceding valid score/color. Don't present that color as freshly measured; show the last successful probe time in the node tooltip. If no valid score exists, stay gray.

For old measurements without a `category`, derive the color from their score using the displayed rubric bands as a visualization-only categorization, while clearly distinguishing historical scoring method where relevant. This colorization does **not** retroactively validate old numeric measurements against the new rubric.

### 4.3 Interaction definition

Source: `experiment/conversations.jsonl` records produced when completed conversations are logged. Use recorded speaker names, not semantic inference.

- Completed conversation between distinct agents A and B => one undirected pair edge `{A,B}`.
- Repeated completed conversation between same pair => increment count on that same edge.
- For logs with >2 participating agents, derive unique unordered participant pairs.
- Reject unknown agents, invalid/self pairs, and duplicate records of one conversation.
- Do not use whispers, reflections, agent proximity, conversational intentions, or LLM-inferred persuasion as edges.
- Do not add any LLM call for network construction.

### 4.4 Cumulative edge semantics

- Each unique agent pair has exactly one edge for the current simulation's cumulative history.
- Count = distinct completed conversations between that pair, including inherited history in a fork.
- Render width as a **bounded, sublinear** function of count (e.g., 1 + c*log(1+count), clamped), so highly active pairs do not hide other links.
- Edge hover displays both names, count, and last conversation timestamp.
- Agent hover displays full name, current retained score/category, last valid probe time, total counted conversations, and distinct interaction partners.
- Clicking a node selects that agent in the existing inspector. Reuse existing selection mechanism; do not duplicate inspector state.
- Optional convenience: click edge to open the most recent matching conversation in the current activity pane, if that transcript is available. Do not require this for initial completion.

**Interpretation:** Edges are conversation frequency, **not proven causal influence**, positive/negative influence, or directed persuasion.

### 4.5 Refresh and efficient aggregation

- Extend the dashboard's existing approximately 1-second poll/repaint cycle; no separate websocket infrastructure is required.
- Compute cumulative counts using **full** conversation history or an equivalent correct incremental aggregate. The current JSON response contains at most the latest 300 conversations: never compute cumulative edges solely from this tail, or counts will shrink when the window advances.
- Prefer exposing lightweight aggregated edge records, not transferring every complete transcript to the browser each second.
- Ensure data access works for live runs and for read-only saved-run endpoints.
- For longer runs, avoid rescanning the complete conversations file on every request if reasonable; an incrementally maintained, reconstructable server-side cache is acceptable, but `conversations.jsonl` must remain the authoritative history.
- Do not depend on the frontend component remaining mounted: refresh/reload/reopen must reconstruct the identical graph.
- Fork inherited conversation logs may be copied into a child's run. Determine the actual fork behavior and ensure inherited events count **exactly once**, with later child conversations accumulating normally.
- Handle switching runs, saved views, backend restart, no opinions yet, and no conversations yet.
- Keep the node layout stable across poll cycles and score/edge updates.

## 5. Suggested engineering scope

Expected files (verify by inspecting repo):

| Path/module | Intended changes |
|---|---|
| `reverie/backend_server/persona/prompt_template/v3_ChatGPT/` | Versioned stance rubric prompt |
| `reverie/backend_server/persona/prompt_template/run_gpt_prompt.py` | Structured response parsing, validation, 0–100 score |
| `reverie/backend_server/opinion_probe.py` | Pass through new score/category/conditions while retaining retrieval |
| `reverie/backend_server/reverie.py` | Log additional stance fields |
| `reverie/backend_server/experiment_logger.py` | Preserve JSONL schema and correct conversation logging if necessary |
| `environment/frontend_server/translator/dashboard.py` | Build cumulative network summary and share it for live/saved views |
| `environment/frontend_server/templates/dashboard/dashboard.html` | Network panel, visualizations, hover, selection, live updates; fix line-graph 0–100 axis |
| `scripts/ci/check_opinion_probe.py` and UI/data tests | New test cases and regression coverage |

Use minimal localized changes and the project's current dependencies/design patterns; don't add a heavy graph library if existing SVG/JS suffices for eight agents.

## 6. Mandatory tests and acceptance checks

### Stance tests

- Valid scores: 0, 19, 20, 39, 40, 49, 50, 51, 60, 61, 80, 81, 100.
- Each of the seven bands maps to its exact category; category/score mismatch and malformed model output must not become a valid record.
- Explicit abstention, asleep, irrelevant memory, or model failure produces `null`, never a fabricated 50.
- New prompt template selected by runtime matches the prompt checked by CI.
- Existing evidence retrieval remains observer-read-only and preserves direct-quote attribution.
- 0 and 100 plot correctly, and the chart handles old 1–100 records without rewriting them.
- New and old `scoring_version` semantics are preserved.

### Network tests

- All agent nodes visible at startup; unrated nodes gray.
- Newly logged completed conversations create edges on the next poll; repeats increase count on the same edge.
- A network with >300 recorded conversations yields accurate cumulative edge counts.
- No invalid/self edges or duplicate counting of one conversation.
- Node color changes only on a new valid score; null leaves last valid color unchanged.
- Live, saved, and forked simulations reproduce expected graph/edge counts on reload, with inherited interactions exactly once.
- Existing line graph, conversation list, roster, agent inspector, and dashboard polling still function.
- Verify color legend and tooltips remain understandable with color vision deficiency (include text labels) and in light/dark themes.
- Ensure user-visible data derived from transcripts/names is safely escaped in DOM rendering.

### Quality checks

- Use existing CI scripts plus focused new tests. Run all relevant local tests; list exact commands and results.
- When a live simulation/API cannot be exercised, use fixtures and disclose precisely what was not verified.
- Compare rubric scorer against the old scorer using frozen evidence if possible, but do not claim improved accuracy merely because it uses a rubric. Check for score clustering near band endpoints or multiples of five.
- No extra LLM calls solely for rendering social edges.
- Document schema changes, scoring semantics, and any backward-compatibility behavior.

## 7. Implementation workflow and deliverables

1. Inspect checked-out code and existing tests. Summarize the relevant call graph and how conversations/stances reach the dashboard.
2. Propose a short plan with files affected, key invariants, and test strategy; identify any contradictions with repo reality.
3. Implement scoring and tests in a contained stage; implement social aggregation and dashboard rendering in a second stage; finally integrate and test both.
4. Keep work in a dedicated feature branch. Do not alter the reviewed baseline branch directly unless explicitly instructed.
5. At completion provide changed file list, behavior summary, tests run (pass/fail), known limitations, migration/compatibility notes, and demo instructions.

### Out of scope

- Separate agent interviews and question batteries.
- Updating simulation personality/state based on measured opinions.
- Learning causal effects from graph connections.
- Directional influence arrows or influence strength inference.
- Large infrastructure/framework refactors unrelated to the two agreed features.
