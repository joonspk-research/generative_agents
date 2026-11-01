# Stance Graph 2.0

Implemented on `codex/stance-graph-v2`, starting at reviewed commit
`8562d994cd18a7fc7d5c7f87789b87c6d22edd9b`. The approved product specification
is `docs/stance-graph-v2-spec.md`.

## Scoring and schema

The active prompt is `datacenter_stance_rubric_v1.txt`. It asks for category
first, then an integer inside that category, an evidence-grounded rationale,
and any explicitly supported conditions. The target is approval of the specific
proposal in its current form. There is one evaluation call per agent, with the
existing three-attempt validation policy; no question battery is introduced.

The seven inclusive bands are:

| Category | Score | Network color |
| --- | --- | --- |
| very_strong_opposition | 0-19 | #A32834 |
| moderate_opposition | 20-39 | #DD645D |
| slight_opposition | 40-49 | #EFAA86 |
| neutral_mixed | 50 | #D5B55C |
| slight_support | 51-60 | #A0CAA0 |
| moderate_support | 61-80 | #48A276 |
| very_strong_support | 81-100 | #17754E |

Every new `opinions.jsonl` reading adds `category`, `conditions`, and
`scoring_version: "rubric_v1"` while preserving existing fields. Valid zero
is not treated as missing. Python rejects fractions, booleans, numeric strings,
unknown categories, out-of-band scores, empty rationales, and malformed conditions.
An explicit abstention has null category and score, with `withheld: "abstained"`.
Exhausted invalid/model responses use `withheld: "evaluator_invalid"`. Sleep,
no-relevant-memory, and empty-memory withholding also produce versioned nulls
(the sleep and relevance labels were since split and renamed; see
`docs/retrieval-methodology-implementation.md`).
50 requires evidence of genuine neutral/mixed views; it is never a fallback.

Evidence selection remains observer-only: relevance-filtered, canonically
deduplicated events/thoughts, with up to ten reserved own-utterance slots within
thirty evidence slots. Speech attribution, chronology, the 0.45 memory similarity
floor, read-only access, and the nonpersistent embedding cache are preserved.
How the statements inside those slots are chosen has since changed — relevance
selects them rather than vetoing a composite ranking, and the probe no longer
calls retrieval at all, so read-only no longer rests on `touch=False`. See
`docs/retrieval-methodology-implementation.md`; the scoring described here is
unaffected.
Only name and age are passed from scratch; broader identity fields remain excluded.
The old text parser and default scorer/probe tuple shapes remain available to
existing replay callers. The sweep tool uses the structured scorer when its
selected template is the active rubric; explicit historical templates retain
their original parser.

## Historical plots

No historical record is rewritten. Rubric rows map 0-100 to the entire vertical
axis; unversioned direct rows retain their original 1-scale coordinate mapping.
The chart identifies legacy and mixed scoring methods and breaks paths at method
changes, as well as at nulls. These instruments are not directly comparable
without calibration. Rationale hover and conversation/whisper/reflection markers
remain. Markers between readings are interpolated positions, not causal estimates.

## Social network and polling

Both `/dashboard/state/` and `/dashboard/run/<sim>/` now return a `network` field:

- `nodes`: all roster names, last valid stance metadata, category/color, last valid
  probe time, conversation count, distinct partner count.
- `edges`: one unordered pair per interaction, cumulative count and latest step/time.
- `conversations`: count of distinct logged conversations (a group chat counts once).
- `bands`: category labels, bounds and colors for the legend.

`translator/social_network.py` reads the full authoritative conversation and
opinion logs, independently of the dashboard's transcript/reading tails. Per-file
byte offsets and compact records avoid reparsing old transcripts each poll;
unchanged summaries are reused. Appends, partial final lines, truncations and
file replacements are handled; a lock protects threaded requests and an eight-run
LRU bounds the number of cached histories. Compact record memory still grows
with the number of conversations/valid readings in each cached run. Reaggregation
on changed records is linear in those compact histories, not just the newest row.

Only nonempty, fully logged transcripts contribute edges. The baseline logger
logs after generating the whole exchange, before simulated chat animations finish;
the network follows that existing logged-completion boundary. No conversation
generation or memory-writing behavior changes. Legacy duplicates use the logger's
step/sorted-speakers/transcript identity; optional `conversation_id` is respected.
Unknown participants and self pairs do not create edges. Group conversations
produce all distinct known participant pairs, but increment each node's total once.

Forking copies experiment files, so only the child's own copied log is read:
following parent logs again would double-count history and import later parent work.
Both conversations and valid opinions are limited to the currently viewed step.
A null or invalid opinion never replaces a node's last valid measurement. Legacy
1-100 scores are colored by the displayed bands for visualization only. Historical
1-10 scores are mapped by relative position to 0-100 for network color; their
original score, scale, and legacy method remain visible in the tooltip.

Frozen-evidence replay outputs also label old and new scoring versions and carry
the new category/conditions, so comparisons do not silently merge instruments.

The new panel sits below the line chart. Stable, name-sorted positions adapt to
two columns on narrow screens and four on wide screens. Edges use a bounded
logarithmic stroke width. Node click/Enter/Space uses the existing agent selection
and inspector. Native SVG titles and accessible labels expose names, category,
last valid time, counts, and partners. The legend includes text as well as color.
The existing polling cycle updates both charts; no new API call is made for edges.

## Verification and demo

From the repository root, with the environment activated:

```bash
python scripts/ci/test_stance_rubric.py
python scripts/ci/check_opinion_probe.py
python scripts/ci/check_retrieval.py
python scripts/ci/check_memory_categories.py
python scripts/ci/check_dashboard_js.py
node scripts/ci/check_stance_graph.js
```

From `environment/frontend_server`, run `python manage.py test translator` and
`python manage.py check`. The rubric tests and JavaScript contract tests are wired
into the existing CI workflow; Django discovers the network aggregation tests.

Optional browser smoke: with Django serving on port 8012 and Playwright available,
run `node scripts/ci/browser_stance_graph.cjs http://127.0.0.1:8012/dashboard`.
Set `NODE_PATH` to your existing Playwright modules if needed. Set `CHROME_BIN`
for a different Chrome installation (the default is macOS Google Chrome).
It intercepts dashboard data with fixtures and never starts a simulation. It
checks polling, node selection, saved view/reload, desktop/mobile, light/dark,
and writes screenshots under `/private/tmp/stance-graph-v2-ui` by default.

To see real data, open `/dashboard`, launch or select a run, and scroll below the
existing stance chart. All nodes appear immediately; completed logged conversations
add edges on the next poll. Set the probe interval or use `call -- probe now` for
new rubric readings. Existing saved runs remain readable without migration.

This validates contracts and rendering, not the scientific accuracy of the rubric.
A paid frozen-evidence comparison has not been run. Assess endpoint/multiple-of-five
clustering before interpreting rubric scores as finer-grained measurements. Existing
probe exception handling and spending-cap timing are unchanged by this feature.

### Local verification results

- `python scripts/ci/test_stance_rubric.py`: 12 tests passed.
- `python manage.py test translator` (frontend directory): 22 tests passed.
- `python manage.py check`: passed.
- The four existing retrieval/probe/memory-category/dashboard-script checks listed
  above: passed; `python scripts/ci/check_repo.py`: passed.
- `node scripts/ci/check_stance_graph.js`: passed.
- `python -m compileall -q reverie/backend_server environment/frontend_server scripts`:
  passed; `git diff --check`: passed.
- Playwright fixture browser smoke: passed on 1440px and 390px viewports, light
  and dark themes. Final screenshots inspected for axis/name clipping.
- `graphify update .`: unavailable (`command not found`); the checkout contains
  no generated Graphify graph to update.
