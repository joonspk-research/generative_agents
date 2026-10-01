# AGENTS.md

Project context for this repository. Read this before changing code or running
experiments.

## What this project is

A fork of Stanford's **Generative Agents** (`joonspk-research/generative_agents`,
UIST '23) — the Smallville simulation where LLM-driven agents keep a memory
stream, retrieve from it, and form higher-level reflections.

The fork exists to run one research question:

> When two agents perform equivalent work but receive unequal outcomes, does the
> reflection pipeline produce **just-world attributions** — the punished agent
> concluding they deserved it, the rewarded agent attributing it to their own
> merit, the observer explaining the gap by disposition rather than chance?

Roles are fixed: **Isabella Rodriguez** = rewardee, **Maria Lopez** = punished,
**Klaus Mueller** = observer.

## Current state of the evidence

Three claims, tracked in `experiments/registry.json` and `docs/JOURNAL.md`:

1. **Headless offline A/B execution is stable** at 100 steps on a local model. Established.
2. **Injected manipulation persists** into associative memory and is separable from control. Established.
3. **Cognition shifts in the just-world direction.** **Open — currently contradicted.**
   Treatment runs produce *fairness critique* ("inequitable treatment", "bias
   towards Isabella"), which is the rival explanation, not the target phenomenon.

Claim 3's testing is blocked on a confound that has now been removed: the
attribution prompt edit and the event injection landed together, so the earlier
runs cannot separate them. `JW_ATTRIBUTION_PROMPTS` is now a runtime switch, which
makes the 2×2 ablation possible.

## Layout

```
reverie/backend_server/reverie.py        simulation loop; headless CLI; event injector
reverie/backend_server/persona/          cognitive modules (perceive/retrieve/plan/reflect)
reverie/backend_server/persona/prompt_template/run_gpt_prompt.py
                                          all prompt wrappers; apply_attribution_framing() here
environment/frontend_server/             Django map UI (optional) + storage/ run artifacts
docs/JOURNAL.md                          append-only lab notebook; STATUS block at top
docs/*.md                                legacy design docs and result summaries (pre-journal)
experiments/registry.json                one machine-readable row per run
analysis/evaluate_runs.py                attribution-language scorer (stdlib only)
analysis/out/                            generated reports (JSON + Markdown)
tools/run_experiment.ps1                 single-run launcher; sets env, logs, registers
tools/run_ablation.ps1                   full 2x2 batch, seed-interleaved
tools/registry.py                        registry CRUD
runs/logs/                               per-run logs + tracebacks (gitignored)
```

`docs/JOURNAL.md` supersedes the older `docs/current_result_summary.md`,
`docs/progress_update_run100.md`, and `docs/merit_run100_result.md`. Those are kept
for history; do not add new findings to them.

## Environment

- **Interpreter:** `.venv311\Scripts\python.exe` (Python 3.11). Only two third-party
  packages are needed: `openai==0.27.0` and `numpy<2`. Django, Selenium, gensim,
  and matplotlib are **not** installed and are not needed.
- **Model:** Ollama at `http://localhost:11434/v1`, `llama3.1:8b` for chat and
  `nomic-embed-text:latest` for embeddings. Start with `ollama serve`.
- **Config:** `reverie/backend_server/utils.py` (gitignored). Holds the API base
  URL and model names.
- `.venv39` is dead — its Python 3.9 interpreter was removed from the machine. Do
  not use it.
- **No Django frontend needed.** Headless mode synthesizes the next environment
  file from movements. Only start `manage.py runserver` if you want to watch the
  map in a browser.

## Running an experiment

```powershell
# one run
.\tools\run_experiment.ps1 -RunId abl_i1_p1_s1 -Condition treatment -Prompts attribution -Steps 100 -Seed 1 -ImportanceTriggerMax 40

# the whole 2x2, 3 seeds, unattended (~2.5 hrs)
.\tools\run_ablation.ps1 -Seeds 1,2,3 -Steps 100

# see the plan without launching anything
.\tools\run_ablation.ps1 -Seeds 1,2,3 -DryRun
```

Then score it:

```powershell
.\.venv311\Scripts\python.exe analysis\evaluate_runs.py --run-id abl_i1_p1_s1 --cells
.\.venv311\Scripts\python.exe analysis\evaluate_runs.py --show-thoughts fairness_critique --limit 5
```

Roughly 12 min per 100-step run on this machine. A 2×2 with 3 seeds is ~2.5 hrs.

## Experiment switches

| Env var | Values | Meaning |
|---|---|---|
| `JW_EXPERIMENT` | `0` / `1` | Inject reward/punishment/observer social-outcome events |
| `JW_ATTRIBUTION_PROMPTS` | `0` / `1` | Causal-attribution reflection prompts vs upstream wording |
| `JW_FRAMING` | `explicit_unfair` / `merit_ambiguous` | Event wording style |
| `JW_IMPORTANCE_TRIGGER_MAX` | integer, default 150 | Reflection cadence. Lower = more insights. Hold constant across cells. |
| `JW_REWARDEE` / `JW_PUNISHED` / `JW_OBSERVER` | agent names | Who plays which role |

The launcher sets all but the last three. Set those manually only if changing
roles.

## Conventions and gotchas

- **`importance_trigger_curr` is a countdown, not an accumulator.** It starts at
  `importance_trigger_max` (150) and each perceived event *subtracts* its
  poignancy (`persona/cognitive_modules/perceive.py:190`). Reflection fires only
  after ~150 points of cumulative poignancy are consumed. Mundane events score 1,
  so at the default an agent reflects roughly **once per 60-70 steps**. A 100-step
  run yields 1-2 insights — not enough to compare conditions. Pass
  `-ImportanceTriggerMax 40` and keep that value identical across every cell of
  an ablation, or it becomes a confound.
- **A zero insight count is a cadence problem, not a null result.** Check
  `importance_trigger_curr` in the run's `scratch.json` before concluding
  anything from empty metrics.
- **Guarding one call site does not guard a category.** `reflect.py` has its own
  `generate_poig_score` separate from the one in `perceive.py`, and both needed
  `None`-guards. Raising the reflection rate makes previously-dead code paths
  live, so re-harden before trusting a long run.
- **The prompt `.txt` templates must stay at upstream wording.** Attribution
  framing is applied at runtime by `apply_attribution_framing()` in
  `run_gpt_prompt.py`. Editing a template to hardcode attribution reintroduces the
  confound that `JW_ATTRIBUTION_PROMPTS` exists to remove.
- **Local models return `None` or empty payloads** where OpenAI models return
  parseable output. Every site that unpacks a model response is a crash site.
  When adding a prompt wrapper, handle `None` and empty payloads.
- **Python 2-style whitespace**: this codebase indents with 2 spaces. Match it.
- **Log every run.** After a run, append an entry to `docs/JOURNAL.md` using the
  template at the top of that file, and update the STATUS block if the state of
  evidence changed. A result that is not journaled will be lost.
- Run artifacts under `environment/frontend_server/storage/` are large. Several
  historical runs (`jw_*`) were committed on branch `main` and removed by
  `ugcs/clean-export`; recover one with
  `git checkout main -- environment/frontend_server/storage/<run_id>`.
- Do not commit `utils.py` (contains keys), `.venv311/`, or `runs/logs/`.

## Interpretation guardrails

The obvious rival explanation is that the agent notices unfairness rather than
rationalizing it. Two consequences:

- Keep event stakes modest. Overt injustice detection suppresses the effect.
- Report the **rival** categories alongside the just-world categories. A rise in
  `deserving`/`self_merit`/`capability` alongside an equal rise in
  `fairness_critique` is not a clean just-world effect.

This simulates attribution behavior in a model. It is not a human-subject study.