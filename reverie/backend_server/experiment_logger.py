"""
Basic experiment logging for datacenter-town runs.

Writes under storage/<sim>/experiment/:
  - run_manifest.json
  - conversations.jsonl
  - events.jsonl
  - agent_snapshots.jsonl
  - outcomes.jsonl
  - opinions.jsonl
"""
import json
import os
from datetime import datetime, timezone

import run_env


class ExperimentLogger:
  def __init__(self, sim_folder, sim_code, fork_sim_code, persona_names,
               scenario_id="datacenter_proposal_v1"):
    self.sim_folder = sim_folder
    self.sim_code = sim_code
    self.fork_sim_code = fork_sim_code
    self.persona_names = list(persona_names)
    self.scenario_id = scenario_id
    self.dir = os.path.join(sim_folder, "experiment")
    os.makedirs(self.dir, exist_ok=True)
    self._logged_convo_keys = set()
    self.current_step = 0

  def set_step(self, step):
    self.current_step = step

  def _path(self, name):
    return os.path.join(self.dir, name)

  def _append_jsonl(self, name, record):
    path = self._path(name)
    with open(path, "a", encoding="utf-8") as f:
      f.write(json.dumps(record, ensure_ascii=False) + "\n")

  def write_manifest(self, extra=None):
    try:
      from utils import llm_provider, chat_model, embedding_provider, embedding_model
    except Exception:
      llm_provider = chat_model = embedding_provider = embedding_model = None

    manifest = {
      "sim_code": self.sim_code,
      "fork_sim_code": self.fork_sim_code,
      "scenario_id": self.scenario_id,
      "persona_names": self.persona_names,
      "created_at": datetime.now(timezone.utc).isoformat(),
      "llm_provider": llm_provider,
      "chat_model": run_env.chat_model(chat_model),
      "run_env": run_env.RUN_ENV,
      "embedding_provider": embedding_provider,
      "embedding_model": embedding_model,
    }
    if extra:
      manifest.update(extra)
    with open(self._path("run_manifest.json"), "w", encoding="utf-8") as f:
      json.dump(manifest, f, indent=2)

  def log_conversation(self, step, curr_time, speakers, utterances, location=None,
                       summary=None):
    if step is None:
      step = self.current_step
    # Deduplicate init/target double-calls within a step.
    key = (step, tuple(sorted(speakers or [])),
           json.dumps(utterances or [], ensure_ascii=False))
    if key in self._logged_convo_keys:
      return
    self._logged_convo_keys.add(key)

    self._append_jsonl("conversations.jsonl", {
      "step": step,
      "time": curr_time.strftime("%B %d, %Y, %H:%M:%S") if curr_time else None,
      "speakers": speakers,
      "utterances": utterances,
      "location": location,
      "summary": summary,
    })

  def log_event(self, step, curr_time, event_type, agent=None, text=None,
                extra=None):
    record = {
      "step": step,
      "time": curr_time.strftime("%B %d, %Y, %H:%M:%S") if curr_time else None,
      "event_type": event_type,
      "agent": agent,
      "text": text,
    }
    if extra:
      record["extra"] = extra
    self._append_jsonl("events.jsonl", record)

  def log_snapshots(self, step, curr_time, personas):
    for name, persona in personas.items():
      scratch = persona.scratch
      self._append_jsonl("agent_snapshots.jsonl", {
        "step": step,
        "time": curr_time.strftime("%B %d, %Y, %H:%M:%S") if curr_time else None,
        "name": name,
        "currently": scratch.currently,
        "act_description": scratch.act_description,
        "act_address": scratch.act_address,
        "chatting_with": scratch.chatting_with,
        "curr_tile": list(scratch.curr_tile) if scratch.curr_tile else None,
      })

  def log_opinions(self, step, curr_time, readings):
    """One row per agent per stance probe, for the dashboard's graph of where
    each agent stands on the datacenter over time. A null score is a probe the
    model gave no usable rating for, and is kept as a gap rather than filled
    in with a number nobody said."""
    for reading in readings:
      self._append_jsonl("opinions.jsonl", {
        "step": step,
        "time": curr_time.strftime("%B %d, %Y, %H:%M:%S") if curr_time else None,
        **reading,
      })

  def log_outcomes(self, step, curr_time, personas, note=None):
    final_currently = {
      name: persona.scratch.currently for name, persona in personas.items()
    }
    self._append_jsonl("outcomes.jsonl", {
      "step": step,
      "time": curr_time.strftime("%B %d, %Y, %H:%M:%S") if curr_time else None,
      "note": note,
      "final_currently": final_currently,
    })


# Module-level handle set by ReverieServer
_LOGGER = None


def set_experiment_logger(logger):
  global _LOGGER
  _LOGGER = logger


def get_experiment_logger():
  return _LOGGER
