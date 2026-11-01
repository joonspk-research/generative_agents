"""
Web dashboard for controlling a simulation and watching its agents.

Talks to reverie.py through files in temp_storage/dashboard/ (see
reverie/backend_server/dashboard_bridge.py). Paths are relative to
environment/frontend_server, like the rest of translator/views.py.
"""
import glob
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from translator.views import _pid_alive as _alive
from translator.social_network import network_summary

log = logging.getLogger("frontend.dashboard")

DASH_DIR = "temp_storage/dashboard"
STATE_FILE = f"{DASH_DIR}/state.json"
CMD_FILE = f"{DASH_DIR}/commands.jsonl"
RESULT_FILE = f"{DASH_DIR}/results.jsonl"
LAUNCH_FILE = f"{DASH_DIR}/launch.json"
BACKEND_DIR = "../../reverie/backend_server"
BACKEND_LOG = f"{BACKEND_DIR}/logs/datacenter-town.log"
USAGE_FILE = f"{BACKEND_DIR}/logs/api_usage.jsonl"

SETTINGS_FILE = f"{DASH_DIR}/settings.json"

# Prices and the cost formula live in the backend's llm/usage.py, shared with
# the simulation's spending cap. That file imports nothing from the backend,
# so it's loaded straight from its path.
_spec = importlib.util.spec_from_file_location(
  "llm_usage", f"{BACKEND_DIR}/llm/usage.py")
_llm_usage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_llm_usage)
PRICES = _llm_usage.PRICES
HISTORY_GLOB = "static_dirs/assets/the_ville/agent_history_init_*.csv"
SIM_NAME = re.compile(r"^[\w-]+$")
# Fields the roster needs every second; the rest is sent for the open agent.
ROSTER_FIELDS = ("name", "first_name", "act_description", "act_pronunciatio",
                 "act_address", "chatting_with", "curr_tile", "currently")


def _read_json(path, default=None):
  try:
    with open(path) as f:
      return json.load(f)
  except (OSError, ValueError):
    return default


def _tail_lines(path, n, max_bytes=256 * 1024):
  try:
    with open(path, "rb") as f:
      f.seek(0, os.SEEK_END)
      f.seek(max(0, f.tell() - max_bytes))
      lines = f.read().decode("utf-8", "replace").splitlines()
  except OSError:
    return []
  return lines[-n:]


def _tail_jsonl(path, n, max_bytes=256 * 1024):
  out = []
  for line in _tail_lines(path, n, max_bytes):
    try:
      out.append(json.loads(line))
    except ValueError:
      pass  # first line of the window can be cut in half
  return out


def _sims():
  sims = []
  for meta_path in glob.glob("storage/*/reverie/meta.json"):
    meta = _read_json(meta_path, {})
    name = meta_path.split("/")[1]
    sims.append({"name": name, "step": meta.get("step", 0),
                 "curr_time": meta.get("curr_time", ""),
                 "fork": meta.get("fork_sim_code"),
                 "maze": meta.get("maze_name"),
                 "mtime": os.path.getmtime(meta_path)})
  return sorted(sims, key=lambda s: -s["mtime"])


def _run_start(sim):
  """The step a run began at. A new run copies everything from the run it
  continues, so anything logged before this step was inherited. Runs are
  never continued in place, so the parent's saved step is where this began."""
  meta = _read_json(f"storage/{sim}/reverie/meta.json", {})
  fork = meta.get("fork_sim_code")
  if not fork or fork == sim:
    return 0
  return _read_json(f"storage/{fork}/reverie/meta.json", {}).get("step", 0)


def _run_log(sim, name, n, start):
  rows = _tail_jsonl(f"storage/{sim}/experiment/{name}", n, max_bytes=2 << 20)
  for r in rows:
    r["inherited"] = (r.get("step") or 0) < start
  return rows


def _opinions(sim, start):
  """Stance readings for the graph. The memory ids and the cosines behind each
  rating stay in the file for analysis; the graph only needs the numbers."""
  rows = _run_log(sim, "opinions.jsonl", 4000, start)
  for r in rows:
    r.pop("evidence", None)
    r.pop("selection", None)
  return rows


def _view_history(sim, persona):
  """Each distinct "currently" an agent has had, from the periodic snapshots,
  to show how their view changed over the run."""
  out = []
  for r in _tail_jsonl(f"storage/{sim}/experiment/agent_snapshots.jsonl",
                       4000, max_bytes=8 << 20):
    if r.get("name") == persona and r.get("currently") and (
        not out or out[-1]["currently"] != r["currently"]):
      out.append({"step": r.get("step"), "time": r.get("time"),
                  "currently": r["currently"]})
  return out


def _schedule_index(schedule, curr_time):
  # Same rule as Scratch.get_f_daily_schedule_index.
  m = re.search(r"(\d{2}):(\d{2}):\d{2}$", curr_time or "")
  if not m or not schedule:
    return None
  elapsed, total = int(m.group(1)) * 60 + int(m.group(2)), 0
  for i, (_, duration) in enumerate(schedule):
    total += duration
    if total > elapsed:
      return i
  return len(schedule) - 1


# Same rule as reverie/backend_server/dashboard_bridge.py:_is_reflection, which
# does this for the live run off ConceptNode objects. This module cannot import
# that one (it reaches utils.py and the API keys), the way _run_env and
# DEFAULT_SETTINGS are also duplicated. check_memory_categories.py runs one
# fixture table through both and fails if they disagree.
#
# Nothing marks a reflection at write time, and depth does not separate it: an
# insight whose evidence is all events has depth 1, exactly like a daily plan
# or a whisper. The evidence is what differs. Insight evidence comes from
# new_retrieve, which draws only on events and thoughts and so never cites a
# chat, while the two thoughts written after a conversation cite exactly the
# last chat. So: evidence that resolves, with no chat in it.
def _is_reflection(node, by_id):
  filling = node.get("filling")
  if node.get("type") != "thought" or not isinstance(filling, list):
    return False
  kinds = {by_id[i].get("type") for i in filling if i in by_id}
  return bool(kinds) and "chat" not in kinds


# Reflections are cut by episode rather than by row: every insight a reflection
# writes shares one timestamp, so a row limit would show the tail of an episode
# as if that were the whole of it.
REFLECTION_EPISODES = 5


def _episodes(nodes):
  """The distinct timestamps in a list of insight nodes, newest first."""
  seen = []
  for n in nodes:
    if n.get("created") not in seen:
      seen.append(n.get("created"))
  return seen


def _saved_agent(sim, name):
  """A saved agent in the same shape the live state uses."""
  mem = f"storage/{sim}/personas/{name}/bootstrap_memory"
  s = _read_json(f"{mem}/scratch.json", {})
  by_id = _read_json(f"{mem}/associative_memory/nodes.json", {}) or {}
  nodes = sorted(by_id.values(), key=lambda n: -n.get("node_count", 0))
  def row(x, kind=None):
    return {"type": x["type"], "created": x.get("created"),
            "description": x.get("description"), "poignancy": x.get("poignancy"),
            **({"lines": x["filling"]} if kind == "chat" and isinstance(x.get("filling"), list) else {})}
  def pick(kind, n):
    return [row(x, kind) for x in nodes if x.get("type") == kind][:n]
  insights = [x for x in nodes if _is_reflection(x, by_id)]
  thoughts = [x for x in nodes
              if x.get("type") == "thought" and not _is_reflection(x, by_id)]
  shown = _episodes(insights)[:REFLECTION_EPISODES]
  counts = {k: sum(1 for x in nodes if x.get("type") == k) for k in ("event", "chat")}
  counts["thought"] = len(thoughts)
  counts["reflection"] = len(_episodes(insights))
  schedule = s.get("f_daily_schedule") or []
  return {
    "name": s.get("name", name), "first_name": s.get("first_name"), "age": s.get("age"),
    "innate": s.get("innate"), "learned": s.get("learned"), "lifestyle": s.get("lifestyle"),
    "living_area": s.get("living_area"), "currently": s.get("currently"),
    "values": s.get("values"), "stake": s.get("stake"),
    "persuadability": s.get("persuadability"),
    "daily_plan_req": s.get("daily_plan_req"), "daily_req": s.get("daily_req"),
    "act_description": s.get("act_description"), "act_pronunciatio": s.get("act_pronunciatio"),
    "act_address": s.get("act_address"), "act_start_time": s.get("act_start_time"),
    "act_duration": s.get("act_duration"), "chatting_with": s.get("chatting_with"),
    "chat": s.get("chat"), "curr_tile": s.get("curr_tile"),
    "path_left": len(s.get("planned_path") or []),
    "schedule": schedule, "schedule_idx": _schedule_index(schedule, s.get("curr_time")),
    "reflect_trigger": [s.get("importance_trigger_curr"), s.get("importance_trigger_max")],
    "memory_counts": counts, "events": pick("event", 15),
    "thoughts": [row(x) for x in thoughts][:15], "chats": pick("chat", 6),
    "reflections": [row(x) for x in insights if x.get("created") in shown],
    "llm": [],
  }


def dashboard_run(request, sim):
  """Read-only view of a saved run, in the same shape as dashboard_state."""
  meta = _read_json(f"storage/{sim}/reverie/meta.json") if SIM_NAME.match(sim) else None
  if not meta:
    return JsonResponse({"error": f"No saved run named {sim}."}, status=404)
  names = meta.get("persona_names", [])
  agent = request.GET.get("agent")
  agents = {n: _saved_agent(sim, n) for n in names}
  start = _run_start(sim)
  manifest = _read_json(f"storage/{sim}/experiment/run_manifest.json", {})
  view = {
    "sim_code": sim, "fork_sim_code": meta.get("fork_sim_code"),
    "step": meta.get("step", 0), "curr_time": meta.get("curr_time"),
    "sec_per_step": meta.get("sec_per_step", 10), "start_step": start,
    "created_at": manifest.get("created_at"), "chat_model": manifest.get("chat_model"),
    # Runs from before staging existed have no run_env; they were production.
    "run_env": manifest.get("run_env") or "production",
    "persona_order": names,
    "roster": [{k: agents[n].get(k) for k in ROSTER_FIELDS} for n in names],
    "agent": agents.get(agent),
  }
  if view["agent"]:
    view["agent"]["history"] = _view_history(sim, agent)
  return JsonResponse({
    "sim": view,
    "conversations": _run_log(sim, "conversations.jsonl", 300, start),
    "events": _run_log(sim, "events.jsonl", 300, start),
    "opinions": _opinions(sim, start),
    "network": network_summary(sim, names, view["step"]),
    "results": [r for r in _tail_jsonl(RESULT_FILE, 400) if r.get("sim") == sim][-60:],
  })


def _backend_status(state):
  """running / idle / finished come from reverie itself; starting and
  stopped are inferred from process liveness."""
  pid = state.get("pid") if state else None
  if pid and _alive(pid) and state.get("status") != "finished":
    return state["status"]
  launch = _read_json(LAUNCH_FILE, {})
  # A launched process that hasn't written its own state yet is starting;
  # one that already reported "finished" is just exiting.
  if _alive(launch.get("pid")) and launch.get("pid") != pid:
    return "starting"
  return "stopped"


def dashboard(request):
  histories = sorted(p.split("static_dirs/assets/")[1]
                     for p in glob.glob(HISTORY_GLOB))
  return render(request, "dashboard/dashboard.html",
                {"histories_json": json.dumps(histories)})


def dashboard_state(request):
  state = _read_json(STATE_FILE)
  status = _backend_status(state)
  agent = request.GET.get("agent")
  data = {"status": status, "sims": _sims(), "settings": _settings(),
          "run_env": _run_env(),
          "results": _tail_jsonl(RESULT_FILE, 40),
          "launch": _read_json(LAUNCH_FILE, {})}
  if state:
    personas = state.pop("personas", {})
    state["roster"] = [{k: personas[n].get(k) for k in ROSTER_FIELDS}
                       for n in state.get("persona_order", []) if n in personas]
    state["agent"] = personas.get(agent)
    sim = state["sim_code"]
    state["start_step"] = start = _run_start(sim)
    if state["agent"]:
      state["agent"]["history"] = _view_history(sim, agent)
    data["conversations"] = _run_log(sim, "conversations.jsonl", 300, start)
    data["events"] = _run_log(sim, "events.jsonl", 300, start)
    data["opinions"] = _opinions(sim, start)
    data["network"] = network_summary(sim, state.get("persona_order", []), state["step"])
    # Results from before runs were tagged have no "sim"; keep showing those.
    data["results"] = [r for r in data["results"] if r.get("sim") in (None, sim)]
  data["sim"] = state
  return JsonResponse(data)


_price = _llm_usage.price


def _cost(row):
  return _llm_usage.cost(row.get("model"), row.get("in", 0),
                         row.get("cached", 0), row.get("out", 0))


# Rows parsed so far, read incrementally so each poll only parses new lines.
_usage = {"offset": 0, "rows": []}


def _usage_rows():
  try:
    size = os.path.getsize(USAGE_FILE)
  except OSError:
    return []
  if size < _usage["offset"]:
    _usage.update(offset=0, rows=[])  # file was replaced
  if size > _usage["offset"]:
    with open(USAGE_FILE, "rb") as f:
      f.seek(_usage["offset"])
      chunk = f.read()
    complete = chunk[:chunk.rfind(b"\n") + 1]
    _usage["offset"] += len(complete)
    for line in complete.decode("utf-8", "replace").splitlines():
      try:
        row = json.loads(line)
      except ValueError:
        continue
      row["cost"] = _cost(row)
      _usage["rows"].append(row)
  return _usage["rows"]


def _totals(rows):
  t = {"calls": len(rows), "chat": 0, "embedding": 0, "errors": 0,
       "in": 0, "cached": 0, "out": 0, "cost": 0.0}
  for r in rows:
    t[r.get("kind", "chat")] = t.get(r.get("kind", "chat"), 0) + 1
    t["errors"] += not r.get("ok", True)
    for k in ("in", "cached", "out"):
      t[k] += r.get(k, 0)
    t["cost"] += r["cost"] or 0
  return t


def _group(rows, key):
  groups = {}
  for r in rows:
    groups.setdefault(r.get(key) or "other", []).append(r)
  return sorted(({"name": k, **_totals(v)} for k, v in groups.items()),
                key=lambda g: -g["cost"])


def dashboard_usage(request):
  rows = _usage_rows()
  sim = request.GET.get("sim") or (_read_json(STATE_FILE) or {}).get("sim_code")
  sec_per_step = (_read_json(f"storage/{sim}/reverie/meta.json", {}) or {}).get("sec_per_step") or 10
  now = time.time()
  midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
  run_rows = [r for r in rows if r.get("sim") == sim]
  recent = [r for r in rows if r["ts"] > now - 300]

  # Average cost per game hour over the steps this run has simulated.
  steps = [r["step"] for r in run_rows if r.get("source") == "step"
           and r.get("step") is not None]
  step_cost = sum(r["cost"] or 0 for r in run_rows if r.get("source") == "step")
  game_hours = ((max(steps) - min(steps) + 1) * sec_per_step / 3600
                if steps else 0)

  ok_chat = [r["secs"] for r in rows if r.get("ok") and r.get("kind") == "chat"][-200:]
  ok_chat_sorted = sorted(ok_chat)
  return JsonResponse({
    "since": rows[0]["ts"] if rows else None,
    "sim": sim,
    "run": _totals(run_rows),
    "today": _totals([r for r in rows if r["ts"] >= midnight]),
    "all": _totals(rows),
    "last5": {**_totals(recent), "minutes": 5},
    "per_game_hour": step_cost / game_hours if game_hours else None,
    "game_hours": game_hours,
    "latency": {
      "avg": sum(ok_chat) / len(ok_chat) if ok_chat else None,
      "p95": ok_chat_sorted[int(len(ok_chat_sorted) * 0.95)] if ok_chat else None,
      "n": len(ok_chat)},
    "agents": _group([r for r in run_rows if r.get("persona")], "persona"),
    "sources": _group(run_rows, "source"),
    "models": _group(rows, "model"),
    "unpriced": sorted({r.get("model") for r in rows if r["cost"] is None}),
    "errors": [{"ts": r["ts"], "model": r.get("model"),
                "status": r.get("status"), "error": r.get("error"),
                "persona": r.get("persona")}
               for r in rows if not r.get("ok", True)][-8:][::-1],
    "prices": {k: list(v) for k, v in PRICES.items()},
  })


def dashboard_log(request):
  return JsonResponse({"lines": _tail_lines(BACKEND_LOG, 300)})


@require_POST
def dashboard_command(request):
  cmd = json.loads(request.body or "{}").get("cmd", "").strip()
  if not cmd:
    return JsonResponse({"error": "Type a command first."}, status=400)
  if _backend_status(_read_json(STATE_FILE)) not in ("idle", "running"):
    return JsonResponse({"error": "The simulation isn't running. Start one "
                                  "first."}, status=409)
  cmd_id = uuid.uuid4().hex[:10]
  os.makedirs(DASH_DIR, exist_ok=True)
  with open(CMD_FILE, "a") as f:
    f.write(json.dumps({"id": cmd_id, "cmd": cmd}) + "\n")
  log.info("dashboard command %s: %s", cmd_id, cmd)
  return JsonResponse({"id": cmd_id})


DEFAULT_SETTINGS = {"autosave_steps": 360, "budget_usd": None,
                    "opinion_steps": 360}


# Same as reverie/backend_server/run_env.py. Git tracks prod-* runs only.
RUN_PREFIXES = {"staging": "stg-", "production": "prod-"}


def _run_env(utils_path=f"{BACKEND_DIR}/utils.py"):
  """run_env from the backend's utils.py, read as text rather than imported
  (it holds API keys). "staging" when it isn't set, matching run_env.py."""
  try:
    with open(utils_path) as f:
      m = re.search(r"""^run_env\s*=\s*["'](\w+)["']""", f.read(), re.M)
  except OSError:
    return "staging"
  return m.group(1) if m else "staging"


def _run_name(sim, env):
  """stg-<name> in staging, prod-<name> in production, matching
  run_env.run_name: a prefix from the other mode is replaced, not stacked."""
  for prefix in RUN_PREFIXES.values():
    if sim.startswith(prefix):
      sim = sim[len(prefix):]
      break
  return RUN_PREFIXES.get(env, RUN_PREFIXES["staging"]) + sim


def _settings():
  return {**DEFAULT_SETTINGS, **(_read_json(SETTINGS_FILE, {}) or {})}


def dashboard_settings(request):
  """GET returns the auto-save and spending-cap settings; POST updates them.
  The running simulation re-reads the file after every step."""
  if request.method != "POST":
    return JsonResponse(_settings())
  body = json.loads(request.body or "{}")
  new = _settings()
  if "autosave_steps" in body:
    try:
      steps = int(body["autosave_steps"] or 0)
    except (TypeError, ValueError):
      return JsonResponse({"error": "Auto-save needs a whole number of steps."}, status=400)
    if not 0 <= steps <= 100000:
      return JsonResponse({"error": "Auto-save must be between 0 (off) and 100000 steps."}, status=400)
    new["autosave_steps"] = steps
  if "opinion_steps" in body:
    try:
      steps = int(body["opinion_steps"] or 0)
    except (TypeError, ValueError):
      return JsonResponse({"error": "Stance readings need a whole number of steps."}, status=400)
    if not 0 <= steps <= 100000:
      return JsonResponse({"error": "Stance readings must be between 0 (off) and 100000 steps."}, status=400)
    new["opinion_steps"] = steps
  if "budget_usd" in body:
    raw = body["budget_usd"]
    if raw in (None, ""):
      new["budget_usd"] = None
    else:
      try:
        cap = float(raw)
      except (TypeError, ValueError):
        return JsonResponse({"error": "The spending cap needs to be a dollar amount."}, status=400)
      if not 0 < cap <= 10000:
        return JsonResponse({"error": "The spending cap must be more than $0 and at most $10,000."}, status=400)
      new["budget_usd"] = round(cap, 2)
  os.makedirs(DASH_DIR, exist_ok=True)
  tmp = SETTINGS_FILE + ".tmp"
  with open(tmp, "w") as f:
    json.dump(new, f)
  os.replace(tmp, SETTINGS_FILE)
  log.info("dashboard settings: %s", new)
  return JsonResponse(new)


@require_POST
def dashboard_launch(request):
  body = json.loads(request.body or "{}")
  fork, sim = body.get("fork", ""), body.get("sim", "").strip()
  history = body.get("history") or None
  if _backend_status(_read_json(STATE_FILE)) != "stopped":
    return JsonResponse({"error": "A simulation is already running. Finish "
                                  "it before starting another."}, status=409)
  if not os.path.exists(f"storage/{fork}/reverie/meta.json"):
    return JsonResponse({"error": f"No saved simulation named {fork}."},
                        status=400)
  if not SIM_NAME.match(sim):
    return JsonResponse({"error": "Use letters, numbers, - or _ for the new "
                                  "name."}, status=400)
  sim = _run_name(sim, _run_env())
  if os.path.exists(f"storage/{sim}"):
    return JsonResponse({"error": f"{sim} already exists. Pick a new name."},
                        status=400)
  allowed = [p.split("static_dirs/assets/")[1] for p in glob.glob(HISTORY_GLOB)]
  if history and history not in allowed:
    return JsonResponse({"error": "Unknown history file."}, status=400)
  try:
    run_steps = int(body.get("run_steps") or 0)
  except (TypeError, ValueError):
    return JsonResponse({"error": "Steps must be a whole number."}, status=400)
  if not 0 <= run_steps <= 100000:
    return JsonResponse({"error": "Steps must be between 0 and 100000."}, status=400)

  args = [sys.executable, "-u", "reverie.py", fork, sim]
  if history:
    args += ["--history", history]
  if run_steps:
    args += ["--run", str(run_steps)]
  os.makedirs(f"{BACKEND_DIR}/logs", exist_ok=True)
  out = open(f"{BACKEND_DIR}/logs/reverie_console.log", "a")
  proc = subprocess.Popen(args, cwd=BACKEND_DIR, stdin=subprocess.DEVNULL,
                          stdout=out, stderr=subprocess.STDOUT,
                          start_new_session=True)
  # Reap it when it exits so a finished run doesn't linger as a zombie that
  # still looks alive to os.kill(pid, 0).
  threading.Thread(target=proc.wait, daemon=True).start()
  os.makedirs(DASH_DIR, exist_ok=True)
  with open(LAUNCH_FILE, "w") as f:
    json.dump({"pid": proc.pid, "fork": fork, "sim": sim, "history": history,
               "at": time.time()}, f)
  log.info("launched reverie pid=%s fork=%s sim=%s history=%s run_steps=%s",
           proc.pid, fork, sim, history, run_steps)
  return JsonResponse({"pid": proc.pid, "sim": sim})
