# Just-World Framing Proposal (Implemented)

Date: May 28, 2026

## Goal
Shift observer attribution away from direct unfairness detection and toward potentially just-world-style rationalization by changing intervention wording.

## Why The Previous Framing Drifted To Fairness Critique
The current treatment repeatedly encoded explicit inequality language such as reward versus punishment for comparable effort. That framing strongly teaches unfairness, so observer memory tends to produce fairness-critique thoughts.

## Key Changes Implemented
1. Added configurable framing mode for just-world event injection in backend runtime.
2. Preserved prior behavior as default mode for backward compatibility.
3. Added a new merit-ambiguous mode that keeps unequal outcomes but frames them with discipline, initiative, preparation, and execution-gap language.
4. Updated observer event wording and keywords per framing mode.

## Implementation Details
Changed file:
- reverie/backend_server/reverie.py

New environment variable:
- JW_FRAMING

Supported values:
- explicit_unfair (default)
  - Uses prior wording with reward, punishment, comparable effort.
- merit_ambiguous
  - Uses wording that implies plausible internal attribution cues.

Behavior by mode:
- explicit_unfair
  - Event keywords: evaluation, reward, penalty, performance
  - Observer keywords: observation, reward, penalty, comparison
- merit_ambiguous
  - Event keywords: evaluation, recognition, feedback, performance
  - Observer keywords: observation, recognition, feedback, comparison

## How To Run With New Framing
PowerShell example:

$env:JW_EXPERIMENT = "1"
$env:JW_REWARDEE = "Isabella Rodriguez"
$env:JW_PUNISHED = "Maria Lopez"
$env:JW_OBSERVER = "Klaus Mueller"
$env:JW_FRAMING = "merit_ambiguous"

Then run the same headless command used previously.

## Expected Experimental Effect
- This does not guarantee just-world fallacy emergence.
- It removes explicit unfairness cues and supplies internal-attribution cues, which is a more suitable condition for observing deservingness or merit rationalization in observer memory.

## Suggested Evaluation Criteria For Next Run
1. Track increase in terms related to merit, discipline, responsibility, competence, deservingness.
2. Track decrease in explicit fairness-critique terms.
3. Compare control and treatment keyword trajectories over time, not only final totals.
