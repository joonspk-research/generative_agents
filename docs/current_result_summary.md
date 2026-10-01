# Current Result Summary

Date: May 28, 2026

## Objective
Verify a just-world-fallacy A/B setup in Generative Agents using local Ollama models, and confirm that treatment-only social outcome manipulation persists in saved artifacts.

## Current Setting
- Base simulation: Smallville / Generative Agents local runtime.
- Experimental control: `JW_EXPERIMENT=1` with observer-targeted event injection.
- Current framing mode: `JW_FRAMING=merit_ambiguous`.
- Current semantic direction: social-outcome events emphasize recognition, discipline, initiative, and corrective feedback rather than explicit unfairness language.
- Current status: merit-framing run100 completed and was committed with its artifacts.

## Final Status
- Completed: local runtime stabilization and long-run A/B execution.
- Completed: persisted control/treatment pair at 20 steps.
- Completed: treatment-only manipulation evidence in associative memory.
- Remaining: deeper attribution-language analysis beyond manipulation presence.

## What Was Fixed
1. Runtime stability hardening
- Defensive parser handling for noisy local-model outputs.
- Save-path guards for missing time fields.
- Movement output directory creation guard.

2. Long-run execution support
- Added non-interactive CLI options in `reverie/backend_server/reverie.py`:
  - `--origin`
  - `--target`
  - `--run-steps`
  - `--offline-auto-advance`
  - `--save-and-exit`
- Added offline environment auto-advance so backend-only runs can progress without frontend-generated environment files.

3. Perception robustness
- Fixed crash in `reverie/backend_server/persona/cognitive_modules/perceive.py` where poignancy prompt calls could return `None`.
- Added safe score fallback (default score = 5) when local model output is invalid.

## Verified Run Results
### Control
- Simulation: `jw_control_run20_d`
- Meta: `step = 20`, `curr_time = February 13, 2023, 00:03:20`
- Path: `environment/frontend_server/storage/jw_control_run20_d/reverie/meta.json`

### Treatment
- Simulation: `jw_treatment_run20_d`
- Meta: `step = 20`, `curr_time = February 13, 2023, 00:03:20`
- Path: `environment/frontend_server/storage/jw_treatment_run20_d/reverie/meta.json`

### Movement Persistence
- Both runs contain movement files `0.json` through `19.json`.

## A/B Evidence
### Present in Treatment
- Isabella reward event embedding key includes:
  - "received major praise and a bonus ..."
- Maria penalty event embedding key includes:
  - "received criticism and no reward ..."
- Klaus observer event description includes:
  - "observed Isabella Rodriguez being rewarded while Maria Lopez was punished for comparable effort"

Primary evidence files:
- `environment/frontend_server/storage/jw_treatment_run20_d/personas/Isabella Rodriguez/bootstrap_memory/associative_memory/nodes.json`
- `environment/frontend_server/storage/jw_treatment_run20_d/personas/Maria Lopez/bootstrap_memory/associative_memory/nodes.json`
- `environment/frontend_server/storage/jw_treatment_run20_d/personas/Klaus Mueller/bootstrap_memory/associative_memory/nodes.json`
- `environment/frontend_server/storage/jw_treatment_run20_d/personas/Klaus Mueller/bootstrap_memory/associative_memory/kw_strength.json`

### Absent in Control
- No matching treatment injection strings in control storage.
- Control keyword strength does not accumulate reward/penalty/comparison/observation dimensions.

Primary control files:
- `environment/frontend_server/storage/jw_control_run20_d/personas/Klaus Mueller/bootstrap_memory/associative_memory/nodes.json`
- `environment/frontend_server/storage/jw_control_run20_d/personas/Klaus Mueller/bootstrap_memory/associative_memory/kw_strength.json`

## Commit History (Latest)
- `91cd0cd6` Add headless run mode and stabilize long A/B runs
- `1f12182e` Harden local A/B simulation runtime

## Current Repo State
Committed:
- `reverie/backend_server/reverie.py`
- `reverie/backend_server/persona/cognitive_modules/perceive.py`
- `docs/implementation_progress.md`

Uncommitted by design:
- `environment/frontend_server/temp_storage/curr_sim_code.json`
- Generated run artifacts under `environment/frontend_server/storage/`

## Practical Conclusion
The experiment infrastructure is now stable enough for long-run offline A/B execution, and the treatment manipulation is clearly persisted and separable from control over 20 steps.

## Suggested Next Analysis
1. Compare reflection/thought text for causal-attribution language shifts.
2. Run multiple seeds/replicates and compute simple frequency metrics (e.g., blame/merit terms per run).
3. Add a small evaluator script to produce repeatable treatment-vs-control summary tables.
4. Run the prompt/event ablation matrix below to separate natural model behavior from our injected structure.

## Suggested Options
To distinguish natural LLM behavior from our changes, the cleanest follow-up is a 2x2 ablation:

| Option | Event Injection | Attribution-Oriented Prompts | What It Tells Us |
| --- | --- | --- | --- |
| 1 | Off | Off | Baseline Smallville behavior with no experiment steering. |
| 2 | Off | On | Pure prompt effect without injected social-outcome framing. |
| 3 | On | Off | Pure event-injection effect with ordinary prompts. |
| 4 | On | On | Current setup: combined effect of injection plus attribution prompts. |

Recommended interpretation rule:
- If option 2 changes thoughts substantially, the prompt is doing most of the work.
- If option 3 changes thoughts substantially, the injected events are doing most of the work.
- If option 4 is much stronger than either 2 or 3 alone, there is an interaction between prompting and memory injection.
