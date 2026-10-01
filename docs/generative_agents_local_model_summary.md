# Generative Agents + Local Models (3 Agents)

## Short answer
For a small run with **3 agents**, you usually **do not need 3 PCs**.

The original `generative_agents` flow is effectively **turn-based / step-based** in practice: model calls are mostly made as part of each simulation step, and many operations are coordinated by a central loop. Even if some code paths are async-capable, that does not automatically mean all three agents are queried in parallel in a way that scales linearly with more PCs.

## What this means for your setup
1. Start with **1 PC** running the simulation + one local model server (Ollama or LM Studio).
2. If latency is high, next upgrade should usually be:
   - a stronger GPU on one host, or
   - one dedicated model host machine (simulation on laptop/desktop, model on another machine).
3. Only consider 3 separate PCs if you rewrite orchestration to explicitly parallelize many LLM calls and route them across workers.

## Why multiple PCs often do not help much (default repo behavior)
- The simulation advances on a shared timeline, and each step has ordering constraints.
- Agent actions and memory updates often depend on prior step outputs.
- If your caller issues requests mostly one-by-one, extra model servers sit idle most of the time.

## Recommended architecture (small experiment)

### Option A (best first try): single machine
- Run simulation process locally.
- Run Ollama or LM Studio local server on same machine.
- Use a smaller instruct model (for example 7B-class) to keep latency acceptable.

### Option B (if your local machine is weak): 2 machines
- Machine 1: simulation/orchestrator
- Machine 2: model server (Ollama or LM Studio)
- Point API base URL from orchestrator to remote model host.

## Ollama vs LM Studio
- **Ollama**: easier headless/server usage, good for scripted API calls.
- **LM Studio**: great UI and easy testing, also exposes OpenAI-compatible local server mode.

For this repo-style integration, either is fine if you have an OpenAI-compatible endpoint layer in your adapter.

## Practical target for 3-agent demo
- Use 1 model endpoint first.
- Keep context windows and prompt sizes moderate.
- Log per-call latency; only optimize parallelism after measuring a bottleneck.

## Migration notes for local model wiring
Because `generative_agents` was built in an older API era, you will typically need an adapter layer that:
- maps prompt calls to your local OpenAI-compatible endpoint,
- handles model name differences,
- optionally adds retry + timeout handling,
- keeps deterministic settings (`temperature`, `top_p`) stable for reproducibility.

## Bottom line
For your stated goal (small experience, 3 agents):
- **Do not start with 3 PCs.**
- Start with **1 PC** (or 2 if you need GPU offload).
- Add more machines only after confirming true parallel request pressure in your modified code path.
