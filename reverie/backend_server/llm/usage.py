"""
Per-call API usage log, one JSON line per request, read by the web dashboard
to show calls, tokens and estimated cost, plus the price table both use.
The dashboard costs calls from their stored tokens, so a price correction
re-costs every past call. The simulation keeps `run_cost` to enforce the
spending cap.

The simulation sets `context` so each call is attributed to the run, agent
and step it was made for.

No imports from the rest of the backend: the dashboard loads this file
directly for PRICES and cost().
"""
import json
import os
import threading
import time

USAGE_FILE = os.path.join(
  os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
  "logs", "api_usage.jsonl")

# sim: run folder name. persona: agent whose turn it is (None outside steps).
# source: "step" during runs, else the command that triggered the call.
context = {"sim": None, "persona": None, "source": None, "step": None}
_lock = threading.Lock()
# Estimated cost of calls made by this process, i.e. the current run (each
# run is its own process). Used for the spending cap.
run_cost = 0.0

# USD per 1M tokens: (input, cached input, output). Standard tier, from
# developers.openai.com/api/docs/pricing (checked 2026-09-29).
PRICES = {
  "gpt-4o": (2.50, 1.25, 10.00),
  "gpt-4o-mini": (0.15, 0.075, 0.60),
  "gpt-4.1": (2.00, 0.50, 8.00),
  "gpt-4.1-mini": (0.40, 0.10, 1.60),
  "text-embedding-3-small": (0.02, 0.02, 0.0),
  "text-embedding-3-large": (0.13, 0.13, 0.0),
}


def price(model):
  # Longest matching prefix, so "gpt-4o-mini" isn't priced as "gpt-4o" and
  # dated names like "gpt-4o-2024-08-06" still match.
  keys = [k for k in PRICES if (model or "").startswith(k)]
  return PRICES[max(keys, key=len)] if keys else None


def cost(model, input_tokens=0, cached_tokens=0, output_tokens=0):
  """USD, or None when the model has no price. Cached tokens are part of
  input_tokens (as OpenAI reports them) and billed at the cached rate."""
  p = price(model)
  if not p:
    return None
  cached = min(cached_tokens or 0, input_tokens or 0)
  return (((input_tokens or 0) - cached) * p[0] + cached * p[1]
          + (output_tokens or 0) * p[2]) / 1e6


def record(kind, provider, model, input_tokens=0, output_tokens=0,
           cached_tokens=0, secs=0.0, ok=True, error=None):
  global run_cost
  run_cost += cost(model, input_tokens, cached_tokens, output_tokens) or 0
  row = {"ts": round(time.time(), 3), "kind": kind, "provider": provider,
         "model": model, "in": input_tokens or 0, "out": output_tokens or 0,
         "cached": cached_tokens or 0, "secs": round(secs, 2), "ok": ok}
  row.update(context)
  if error is not None:
    row["error"] = f"{type(error).__name__}: {error}"[:300]
    row["status"] = getattr(error, "status_code", None)
  try:
    with _lock:
      os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
      with open(USAGE_FILE, "a") as f:
        f.write(json.dumps(row) + "\n")
  except OSError:
    pass  # usage tracking must never break a simulation step
