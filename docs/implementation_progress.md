# Generative Agents Local-Model Implementation Progress

## Goal
- Clone `joonspk-research/generative_agents`
- Choose an exact local Ollama model for initial run
- Track implementation steps and outcomes

## Progress Log
- [x] Created progress tracker
- [x] Clone repository
- [x] Verify repository structure
- [x] Verify Ollama availability
- [x] Select exact model
- [x] Record recommended next implementation steps
- [x] Add local runtime config file (utils.py)
- [x] Make gpt_structure.py model and endpoint configurable
- [x] Make backend test.py use configurable model and endpoint
- [x] Syntax-check modified Python files
- [x] Check local Python runtime availability
- [x] Install Python dependencies in a virtual environment
- [x] Start environment server (Django)
- [x] Start backend simulation server
- [~] Run 5-step smoke test (execution path verified, output quality still unstable)
- [x] Add legacy completion prompt-continuation guardrails in GPT_request
- [x] Execute timed smoke test: run 1
- [x] Execute timed smoke test: run 5

## Decisions
- Exact model for first run: llama3.1:8b (already installed locally).
- Why this model: good quality/speed balance for multi-agent dialogue while keeping VRAM and latency manageable for a 3-agent demo.
- Current repo execution pattern is sequential in the core step loop (persona.move is called in a for-loop), so distributed per-agent machines are not required for this stage.
- Legacy OpenAI engine names in the repo are now mapped to configured local model names in gpt_structure.py.
- Quick adherence probes with completion-style prompts showed gemma4:latest and gpt-oss:20b frequently returned empty first-line outputs under this repo's stop-token settings, while llama3.1:8b returned non-empty outputs and progressed farther.
- Added a stricter continuation-only instruction prefix in GPT_request to reduce local-model meta commentary in legacy completion chains.

## Verified State
- Repository cloned at: c:/Users/mtchoy/Desktop/peter/generative_agents
- Ollama version: 0.24.0
- Confirmed installed candidates: llama3.1:8b, qwen3.6:latest, gemma4:latest, gpt-oss:20b, others
- Python in PATH: 3.11.9
- Python launcher (py) available after Python 3.9 install
- Python 3.9 installed and used for venv: .venv39
- Dependencies installed successfully from requirements.txt
- Django environment server confirmed running at http://127.0.0.1:8000/
- Local model endpoint check passed for llama3.1:8b via /v1/chat/completions
- Backend smoke-test reaches schedule generation, but local model often returns meta-text ("Here is the completed hourly breakdown...") that degrades downstream planning quality
- Probe result: llama3.1:8b produced non-empty completion continuation; gemma4:latest and gpt-oss:20b produced empty outputs in first-line stop-token tests
- Follow-up validation of the new continuation guardrail is pending a clean rerun of the backend smoke test

## Timed Smoke Test Results (May 25, 2026)
- Run command: run 1
- Result: failed
- Wall time: 108.15s
- Primary failure: TypeError in plan path when generate_act_obj_desc returns None and caller subscripts [0]
- Stack location observed: reverie/backend_server/persona/cognitive_modules/plan.py (generate_act_obj_desc call site)

- Run command: run 5
- Result: failed (same failure signature)
- Wall time: 108.16s
- Interpretation: failure occurs in early planning/generation path before step-count differences matter

## Immediate Next Fix
- Add defensive fallback handling for run_gpt_prompt_act_obj_desc return value in plan.py (handle None/empty safely).
- Add similar defensive fallback in save path to avoid secondary crash when act_start_time is None.

## Post-Fix Validation (May 27, 2026)
- Applied both requested fixes:
	- Defensive fallback for generate_act_obj_desc in plan path.
	- Defensive None guard for act_start_time in scratch save path.
- Re-ran timed smoke test (run 1):
	- Wall time: 145.89s
	- Previous crash points were bypassed successfully.
	- New failure appears later in task decomposition parsing:
		- ValueError in run_gpt_prompt_task_decomp cleanup when parsing duration token like "5)".
		- Stack points to persona/prompt_template/run_gpt_prompt.py (__func_clean_up for task decomposition).

## Recommended Next Steps
- Tune model choice and prompt adherence for completion-style calls (likely try gemma4:latest or gpt-oss:20b).
- Add stricter output post-processing in GPT_request for legacy prompt chains that expect short fragments.
- Re-run the 3-agent smoke test (run 1-5) and validate that activity strings are coherent and not meta-commentary.

## A/B Stability Unblock and Verification (May 27, 2026)
- Applied additional runtime hardening after follow-on crashes during A/B runs:
	- Hardened task decomposition cleanup in `run_gpt_prompt.py` to parse noisy numbering/duration tokens from local model output.
	- Added save guards in `scratch.py` for missing `curr_time`/`act_start_time` during early-step persistence.
	- Added movement output directory creation in `reverie.py` before writing movement step files.
- Re-ran paired simulations after fixes:
	- Control: `jw_control_run1_c`
	- Treatment: `jw_treatment_run1_c` with `JW_EXPERIMENT=1`, `JW_REWARDEE=Isabella Rodriguez`, `JW_PUNISHED=Maria Lopez`, `JW_OBSERVER=Klaus Mueller`
- Persistence check:
	- Both control and treatment now save cleanly with `step: 1` in `reverie/meta.json`.
- Injection check:
	- Treatment contains injected just-world event traces in associative memory files:
		- Isabella: "received major praise and a bonus ..."
		- Maria: "received criticism and no reward ..."
		- Klaus observer event: "observed Isabella Rodriguez being rewarded while Maria Lopez was punished for comparable effort"
	- Control has no matching reward/penalty observer injection strings.
- Conclusion:
	- A/B setup now executes to a persisted state and treatment-only manipulation is confirmed present in stored memory artifacts.
	- Next step for effect testing is multi-step runs (e.g., run 20-50) and attribution-content comparison across reflections/thought traces.

## Longer-Run Execution Note (May 28, 2026)
- Initial non-interactive `run 20` attempts (`jw_control_run20_a`, `jw_treatment_run20_a`) created bootstrap artifacts but remained at `step: 0`.
- Diagnosis: piping all CLI inputs in one shot is not reliable for longer runs in this environment, even though it worked for the shorter `run 1` verification.
- Follow-up: interactive line-by-line launches (`jw_control_run20_b`, `jw_treatment_run20_b`) successfully entered live generation work (`generate_wake_up_hour`, schedule/task decomposition traces), which indicates the control path is running and the earlier `step: 0` issue is input-delivery related rather than a newly introduced runtime crash.
- Remaining work: let the interactive `run 20` pair finish, then compare downstream reflection/associative-memory content for attribution differences beyond the treatment injection itself.

## Headless Long-Run A/B Verification (May 28, 2026)
- Implemented a non-interactive CLI path in `reverie.py`:
	- `--origin`, `--target`, `--run-steps`, `--offline-auto-advance`, `--save-and-exit`
	- Added offline environment auto-advance (synthesizes `environment/{step}.json` from movement outputs) to support multi-step backend-only execution without frontend coordination.
- Fixed a long-run crash in `perceive.py` where local-model poignancy calls could return `None`:
	- Added safe fallback parsing in `generate_poig_score` (defaults to score 5 on invalid output).
- Fresh long runs completed successfully:
	- Control: `jw_control_run20_d`
	- Treatment: `jw_treatment_run20_d`
	- Both persisted at `step: 20` with matching `curr_time: February 13, 2023, 00:03:20`.
- A/B evidence in persisted memory:
	- Treatment contains repeated just-world injections across steps:
		- Isabella "received major praise and a bonus..."
		- Maria "received criticism and no reward..."
		- Klaus observer event about rewarded Isabella vs punished Maria.
	- Control contains none of these injection strings.
	- Keyword-strength contrast for Klaus (`kw_strength_event`):
		- Treatment: `reward: 20`, `penalty: 20`, `comparison: 20`, `observation: 20`
		- Control: no reward/penalty/comparison/observation keyword accumulation.
- Interpretation:
	- Treatment manipulation now survives and accumulates over a 20-step run, while control remains free of the injected social-outcome traces.
	- This confirms stable long-run manipulation persistence suitable for downstream attribution-analysis experiments.
