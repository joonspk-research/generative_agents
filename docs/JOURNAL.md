# Project Journal

Append-only lab notebook for this project. **Read the STATUS block first** — it is
rewritten on every substantive change and is the fastest way to recover context.

Machine-readable companion: [`experiments/registry.json`](../experiments/registry.json)
(one row per run). Metrics: [`analysis/evaluate_runs.py`](../analysis/evaluate_runs.py).

---

## STATUS

_Last updated: 2026-10-01_

**Question.** Does the Generative Agents reflection pipeline produce just-world
attributions (victim-deserves-it / observer-blames-the-loser) when two agents do
equivalent work but receive unequal outcomes?

**Answer so far.** Infrastructure: yes, solved. Manipulation: yes, it persists in
memory. Cognitive direction: **not yet** — the pipeline currently produces
*fairness critique*, not just-world rationalization. The explicit-unfair framing
made agents call the manipulation biased; the merit-ambiguous framing moved
vocabulary toward performance/merit but did not yet yield victim-deserving logic.

**Three claims, each with its evidence status:**

| # | Claim | Status |
|---|-------|--------|
| 1 | Headless, offline A/B execution is stable at 100 steps on a local model | **Established** |
| 2 | Treatment-only injection is persisted and separable from control | **Established** |
| 3 | Cognition shifts in the just-world direction | **Open — currently contradicted** |

**Two measurement defects found (both fixed, both were distorting results):**

1. **Confound.** The attribution prompt edit and the event injection landed
   together, so no earlier run could separate them. Now unblocked by
   `JW_ATTRIBUTION_PROMPTS`, a runtime switch.
2. **Underpowered reflection.** `importance_trigger_curr` is a *countdown* from
   150, decremented by each event's poignancy (`perceive.py:190`). At the default
   the observer reflects only ~once per 60-70 steps — 1-2 insights per 100-step
   run. Every earlier 100-step run was too small to compare conditions. Now
   configurable via `-ImportanceTriggerMax`; 40 yields ~8 reflections per 25 steps.

**Current best signal (n=1, `smoke_i1_p1_refl40_v3`).** 67 insights scored.
Observer and punished agent both produced `deserving` hits attributing the
outcome gap to Maria's disposition (*"has execution gaps in her work"*) rather
than to chance. Direction is correct but the punished agent shows as much
fairness critique as self-blame. A hint, not a result.

**Environment.** Python 3.11 in `.venv311` (minimal deps: `openai==0.27.0`,
`numpy<2`). The old `.venv39` is dead — its Python 3.9 interpreter was removed
from the machine. Django/Selenium are **not** installed and not needed: use
headless mode. Model served by Ollama at `http://localhost:11434/v1`.

**Next actions.**
1. Run the 2x2 ablation, 3 seeds, 100 steps, `-ImportanceTriggerMax 40`:
   `.\tools\run_ablation.ps1 -Seeds 1,2,3 -Steps 100`
2. Judge on `deserving`+`capability` vs `fairness_critique` in treatment cells
   relative to control cells — not on absolute hit counts.
3. Keep event stakes modest; overt injustice detection is the main rival
   explanation and must stay weak for the effect to be interpretable.
4. Only then decide whether the framing needs another nudge or whether the
   just-world effect is genuinely absent in this architecture.

---

## Entry template

Copy this block for every new entry. Keep entries short and concrete; the point
is to be able to reconstruct *why* a decision was made months later.

```markdown
### YYYY-MM-DD - <short title>

- **Type:** infra | run | analysis | decision | failure
- **Hypothesis:** what we expected to see (one sentence)
- **Setup:** run_id(s), condition, injection, prompts, framing, steps, model
- **Result:** what actually happened (numbers, quotes)
- **Learned:** the interpretation, and what it rules in / out
- **Next:** the concrete next action
```

---

## Entries

### 2026-05-25 - Smoke tests fail on local model output

- **Type:** failure
- **Hypothesis.** `llama3.1:8b` via Ollama can drive the full simulation loop.
- **Setup.** `run 1` and `run 5` against `base_the_ville_isabella_maria_klaus`.
- **Result.** Both failed after ~108s with the same signature:
  `TypeError` in `plan.py` when `generate_act_obj_desc` returned `None` and the
  caller subscripted `[0]`.
- **Learned.** Local models return empty/None payloads where OpenAI models return
  parseable JSON. Every prompt wrapper that indexes into a response is a crash
  site. This shaped all later hardening.
- **Next.** Add defensive fallbacks at every response-unpacking site.

### 2026-05-25 - Model selection

- **Type:** decision
- **Hypothesis.** Some locally installed model can produce usable structured output.
- **Setup.** Candidates: `llama3.1:8b`, `gemma4:latest`, `gpt-oss:20b`.
- **Result.** `gemma4:latest` and `gpt-oss:20b` frequently returned empty
  first-line output under this repo's stop-token settings. `llama3.1:8b` returned
  non-empty output and progressed farther.
- **Learned.** Output *shape* adherence, not raw model quality, is the binding
  constraint. Larger models were not more useful here.
- **Next.** Standardize on `llama3.1:8b`; add a continuation-only prefix to
  `GPT_request` because local models add meta commentary to legacy completion prompts.

### 2026-05-27 - Runtime hardening

- **Type:** infra
- **Hypothesis.** The identified crash sites are the only blockers.
- **Setup.** `run 1` re-run post-fix.
- **Result.** Simulation advanced past the previous failure point.
- **Learned.** `perceive.py` had a second `None` path (poignancy prompt) and
  `scratch.py` crashed on save when `act_start_time` was unset. Defensive
  fallbacks belong at all three.
- **Next.** Add headless CLI mode so no browser is required for A/B runs.

### 2026-05-28 - Injection persists; cognition points the wrong way

- **Type:** run
- **Hypothesis.** Injected reward/punishment events will survive into reflection
  and produce just-world attributions.
- **Setup.** `jw_control_run20_d` vs `jw_treatment_run20_d`, 20 steps, then
  `jw_control_run100_a` vs `jw_treatment_run100_a`, 100 steps.
- **Result.** Injection persisted cleanly: treatment observer memory accumulated
  `reward/penalty/comparison/observation: 100`; control showed no such signal.
  But treatment thoughts read *"Inequitable treatment of Maria Lopez"*, *"Lack of
  fairness in evaluation criteria"*, *"Bias towards Isabella Rodriguez"*.
- **Learned.** Claim 2 established. Claim 3 **contradicted** — the effect is real
  but it is fairness critique, the opposite of just-world rationalization. The
  event wording was doing the teaching, not just triggering retrieval.
- **Next.** Soften event wording so outcomes look effort-linked rather than
  explicitly unfair; run matched 100-step A/B again.

### 2026-05-28 - Merit-ambiguous framing

- **Type:** run
- **Hypothesis.** Removing explicit unfairness language will move cognition from
  fairness critique toward merit attribution.
- **Setup.** `jw_treatment_merit_run100_a`, `JW_FRAMING=merit_ambiguous`, 100 steps
  (~702s wall clock).
- **Result.** Lexical content shifted toward performance/merit framing
  (`recognition/discipline/initiative/corrective feedback`); explicit unfairness
  critiques dropped. Victim-deserving/blame language still weak.
- **Learned.** Direction of influence confirmed and manipulable, but the effect is
  an *intermediate stage*, not the target phenomenon.
- **Next.** Mild dispositional language in observer-facing events; keep stakes
  modest; track deservingness terms as a dedicated metric.

### 2026-10-01 - Environment rebuilt; 2x2 ablation unblocked

- **Type:** infra
- **Hypothesis.** The confound between event injection and prompt wording can be
  removed by making the prompt edit a runtime switch.
- **Setup.** Python 3.11 (`.venv39` interpreter had been deleted from the
  machine); Ollama 0.24.0 restarted; `llama3.1:8b` + `nomic-embed-text` verified.
- **Result.** Four changes landed:
  1. `.venv311` created with only `openai==0.27.0` and `numpy<2`. Verified the
     headless backend's entire third-party import surface is just those two —
     `numpy` and `openai`.
  2. Removed the module-level `from selenium import webdriver` in `reverie.py`.
     It was unused by every code path except the path tester, and it forced a
     heavyweight dependency into headless runs.
  3. Reverted the two prompt `.txt` templates to upstream wording and moved the
     attribution framing into `apply_attribution_framing()` in `run_gpt_prompt.py`,
     gated on `JW_ATTRIBUTION_PROMPTS`. Verified both branches render correctly.
  4. Added the journal/registry/evaluator tooling this file belongs to.
- **Learned.** The earlier hardcoded prompt edit was itself a confound: there was
  no way to run the "injection on, prompts off" cell, because the prompt change
  was baked into the templates. That is why the ablation could not be run before.
- **Next.** Run the 2x2: injection (0/1) x attribution prompts (0/1), 3 seeds,
  100 steps, and evaluate with `analysis/evaluate_runs.py`.

### 2026-10-01 - Reflection cadence was throttling the whole study

- **Type:** infra
- **Hypothesis.** A 25-step treatment run would produce enough reflection
  insights to score attribution language.
- **Setup.** `smoke_i1_p1_5step`, then `smoke_i1_p1_12step`, then
  `smoke_i1_p1_refl40_v3` (25 steps, `-ImportanceTriggerMax 40`).
- **Result.** The 5- and 12-step runs produced **zero** reflection insights.
  Inspecting `scratch.py` showed why: `importance_trigger_curr` is a *countdown*,
  not an accumulator. It starts at `importance_trigger_max` (150) and each
  perceived event **subtracts** its poignancy (`perceive.py:190`), so reflection
  fires only once ~150 points of cumulative event poignancy have been consumed.
  Mundane events score 1, so at the default the observer reflects roughly **once
  per 60-70 steps** — one or two insights per 100-step run. Comparing
  attribution language across conditions on 1-2 data points is not viable.
- **Learned.** Every previous 100-step run in this project was almost certainly
  underpowered for the same reason, independent of prompt wording. This is a
  design defect in the measurement setup, not a property of the phenomenon.
  Lowering the threshold to 40 made reflection fire ~8 times in 25 steps.
- **Next.** `-ImportanceTriggerMax` is now a launcher parameter. Hold it identical
  across all cells so it is not itself a confound, and use 40 going forward.

### 2026-10-01 - First scoreable just-world signal

- **Type:** run
- **Hypothesis.** With reflection actually firing, the merit-ambiguous treatment
  produces capability/deserving attributions about the punished agent.
- **Setup.** `smoke_i1_p1_refl40_v3`, treatment + attribution prompts,
  `merit_ambiguous`, 25 steps, `reflect_trigger_max=40`, 307s wall clock.
- **Result.** 67 reflection insights scored across three agents. Manipulation
  present (`comparison/observation/recognition/feedback: 25` each). Attribution
  hits: punished agent Maria Lopez 2 `deserving` + 1 `fairness_critique`;
  observer Klaus Mueller 1 `deserving`; rewardee Isabella 1 `capability`.
  Representative thoughts: *"Maria Lopez has execution gaps in her work"* and
  *"Maria Lopez's lack of preparation and missed details are likely due to her
  inconsistent work habits."*
- **Learned.** Direction is right — the observer now attributes the outcome gap
  to Maria's disposition rather than to chance, which is the just-world pattern.
  But n=1 run, and the punished agent shows as much fairness critique as
  self-blame, so this is a hint, not a result.
- **Next.** Run the full 2x2 at 3 seeds. The interesting number is not absolute
  hit count but whether `deserving`/`capability` beats `fairness_critique` in
  treatment cells and not in control cells.

### 2026-10-01 - Scorer pools would have hidden the failure modes

- **Type:** infra
- **Hypothesis.** The evaluator aggregates runs into 2x2 cells correctly.
- **Setup.** Ran the scorer across all registered runs including the deliberately
  broken ones.
- **Result.** Cell `inj=1,prompts=1` reported `n=4`. Three of those runs were the
  5-step, 12-step, and crashed runs — all with zero insights. Because rates are
  normalized per 100 thoughts, pooling a zero-insight run contributes 0 hits over
  0 thoughts and silently drags every rate down. The cell looked like it had four
  replicates when it had one.
- **Learned.** Per-100 normalization is not self-protecting. Any run that did not
  produce insights must be excluded and *visibly* excluded, otherwise a broken run
  reads as a null result — which is precisely the failure this project already
  made once with the reflection cadence.
- **Next.** Added `cell_eligible()`: excludes failed runs and zero-insight runs
  from aggregates, and the report names them in an explicit exclusion note.

### 2026-10-01 - Two more crash sites found while validating

- **Type:** failure
- **Hypothesis.** The existing `None`-guards covered the known crash sites.
- **Setup.** 25-step run with the lowered reflection threshold.
- **Result.** Crash at `reflect.py:80` — `run_gpt_prompt_event_poignancy(...)[0]`
  on `None`. This is the *thought* poignancy path in `reflect.py`, distinct from
  the *event* path already guarded in `perceive.py`. It only becomes reachable
  once reflection fires often, which is why it never appeared in earlier runs.
  Separately, the launcher itself had a bug: `$ErrorActionPreference = 'Stop'`
  turns Python's stderr traceback into a terminating `NativeCommandError`, which
  aborted the script before it could write the registry row or preserve the
  traceback.
- **Learned.** Guarding one call site does not guard a category. Whenever the
  reflection cadence changes, previously-dead code paths become live and must be
  re-hardened. Also: a wrapper script that swallows a subprocess traceback is
  worse than no wrapper, because it hides the one artifact you need.
- **Next.** Added the same `_safe_score` guard to `reflect.py`; launcher now
  writes stderr to a separate file and logs the registry row regardless of exit
  code.