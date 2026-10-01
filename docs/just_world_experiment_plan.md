# Just World Fallacy Experiment Plan for Generative Agents

## Goal
Test whether the Smallville / Generative Agents reflection pipeline produces just-world style attributions when two or more agents experience the same behavior but receive different outcomes.

## Core Hypothesis
If identical actions are paired with arbitrary rewards or punishments, the reflection engine will generate biased higher-level beliefs that rationalize the outcome, for example:
- rewarded agent: "My hard work is paying off"
- punished agent: "I must not be doing this correctly"
- observer agent: "Agent B is lazy / less capable"

## Why This Repo Can Support It
The architecture already separates:
- memory stream and short-term state in [scratch.py](../reverie/backend_server/persona/memory_structures/scratch.py)
- reflection triggering and thought generation in [reflect.py](../reverie/backend_server/persona/cognitive_modules/reflect.py)
- prompt construction for reflection-related generations in [run_gpt_prompt.py](../reverie/backend_server/persona/prompt_template/run_gpt_prompt.py)

That makes it suitable for a controlled attribution experiment without rewriting the whole simulator.

## Experimental Design

### Agents
Use three agents:
- Agent A: reward recipient
- Agent B: punishment recipient
- Agent C: observer

A and B should start with the same seed memories, similar traits, and the same task schedule.
C should observe both A and B, but not receive the reward manipulation.

### Manipulation
For the same observable behavior, inject different world-state outcomes:
- A receives praise, bonus, or positive feedback
- B receives criticism, penalty, or negative feedback
- C observes both events

Keep the actual action identical across all agents for each trial.

### Conditions
Run at least two conditions:
1. Control: identical action, identical outcome
2. Treatment: identical action, unequal outcome

Optional third condition:
3. Reversed treatment: swap rewards between A and B

## What to Change

### 1. Environment Logic
Add a world event injector that attaches arbitrary reward/punishment text after a shared action completes.
Possible place to wire this:
- [reverie.py](../reverie/backend_server/reverie.py)
- agent state transitions in [plan.py](../reverie/backend_server/persona/cognitive_modules/plan.py)

The injector should emit structured events such as:
- "Agent A received praise for the task"
- "Agent B received a reprimand for the same task"

### 2. Reflection Prompting
Adjust the reflection prompt used by:
- [run_gpt_prompt_focal_pt](../reverie/backend_server/persona/prompt_template/run_gpt_prompt.py)
- [run_gpt_prompt_insight_and_guidance](../reverie/backend_server/persona/prompt_template/run_gpt_prompt.py)

Current behavior asks the model to synthesize insights from memory. For the experiment, bias the prompt toward attribution language, for example:
- "What do these events suggest about why this happened?"
- "What does this say about the character, effort, or abilities of the people involved?"

Do not ask the prompt to explicitly mention fairness or bias, because that would suppress the effect you want to measure.

### 3. Memory Weighting
Increase the salience of reward / punishment events so they remain visible during reflection.
Relevant knobs are in [scratch.py](../reverie/backend_server/persona/memory_structures/scratch.py):
- `importance_trigger_max`
- `importance_ele_n`
- `kw_strg_event_reflect_th`
- `kw_strg_thought_reflect_th`

The goal is to ensure the manipulated outcome survives retrieval long enough to influence reflection.

## Logging Plan
Save the following for each trial:
- action performed
- actual outcome for A/B/C
- focal points selected during reflection
- generated insights / thoughts
- evidence nodes used by reflection
- any attribution language or fairness language

Recommended outputs:
- raw reflection output
- parsed reflection thoughts
- a manual label: just-world / self-serving / neutral / system-aware

## Analysis Plan
Compare reflections across conditions and agents.

### Success Signal
The experiment succeeds if biased explanations appear more often in the treatment condition than in the control condition, for example:
- A interprets reward as proof of merit
- B interprets punishment as personal deficiency
- C attributes observed outcome differences to personal traits instead of random assignment

### Failure Signal
The experiment is weak if the model consistently says:
- "this looks unfair"
- "the system is random"
- "the outcome was assigned arbitrarily"

That would indicate the prompt needs to be more character-anchored, or the model is too overtly fairness-aware for the effect you want.

## Practical Trial Procedure
1. Start from the 3-agent base simulation.
2. Give A and B the same task schedule and seed memories.
3. Inject one or more identical task completions.
4. Randomly reward A and punish B for the same action.
5. Let memory accumulate until reflection triggers.
6. Extract generated thoughts from the reflection path.
7. Compare A, B, and C outputs manually and by keyword tagging.

## Suggested Minimum Viable Version
Start with a small, repeatable trial:
- one shared task
- one reward/punishment event
- one reflection cycle
- one observer agent

That is enough to see whether the pipeline produces attribution bias before you expand the study.

## Risks / Caveats
- Modern LLMs may explain the manipulation as a system issue instead of a just-world rationalization.
- If the reward signal is too weak, it may not survive retrieval.
- If the prompt is too explicit about fairness, the model may self-correct.
- This is a simulation of attribution behavior, not a human-subject psychology study.

## Next Implementation Step
Implement the smallest world-event injector first, then patch the reflection prompt only as much as needed to make the causal attribution question explicit.
