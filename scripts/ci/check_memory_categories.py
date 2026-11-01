"""
Rules for the Mind tab's memory categories, checked in CI
(.github/workflows/ci.yml). Run from the repo root:
python scripts/ci/check_memory_categories.py

The dashboard splits what an agent stores into events, conversations, thoughts
and reflections. Two things make that harder than it sounds:

- Nothing marks a reflection at write time, and depth does not separate one
  from an ordinary thought: an insight whose evidence is all events has depth 1,
  exactly like a daily plan. The rule used instead is structural -- evidence
  that resolves to nodes, with no chat among them, because insight evidence
  comes from new_retrieve, which draws only on seq_event and seq_thought. That
  rule exists twice: once over ConceptNode objects for the live run, once over
  the dicts in nodes.json for saved runs, because the frontend cannot import
  backend modules (they reach utils.py and the API keys). This runs one table
  of nodes through both and fails if they disagree -- a split-brain Mind tab
  that categorises a saved run differently from the run it was saved from.
- Reading memory for the dashboard must not change it. The dashboard polls
  every second, so anything the payload builder touches, it touches constantly:
  a new_retrieve call here would hand a recency score of 1 to whatever it read
  on every poll, and an in-place sort would reorder the agent's own memory
  stream, since seq_thought is the list itself and not a copy.
"""
import ast
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BRIDGE = os.path.join(ROOT, "reverie", "backend_server", "dashboard_bridge.py")
TRANSLATOR = os.path.join(ROOT, "environment", "frontend_server", "translator",
                          "dashboard.py")

problems = []


def tree(path):
  with open(path, encoding="utf-8") as f:
    return ast.parse(f.read())


def func(mod, name, where):
  """A top-level or nested function by name, as an ast node."""
  found = [n for n in ast.walk(mod)
           if isinstance(n, ast.FunctionDef) and n.name == name]
  if not found:
    problems.append(f"{where}: {name} is gone. Either it was renamed, in which "
                    f"case this check has to follow it, or the categories are "
                    f"no longer being worked out and nothing proves the two "
                    f"halves of the dashboard agree.")
  return found[0] if found else None


def extract(path, names, where):
  """The named functions, pulled out as source and run on their own.

  Neither file can simply be imported: dashboard_bridge.py reaches utils.py and
  the API keys, and translator/dashboard.py needs Django settings configured.
  These functions depend on nothing but their arguments, so lifting them out
  runs the real code without dragging either world in.
  """
  mod = tree(path)
  ns = {}
  for name in names:
    node = func(mod, name, where)
    if node is None:
      return None
    exec(compile(ast.Module([node], []), path, "exec"), ns)
  return ns


class Node:
  """A ConceptNode as far as _is_reflection is concerned."""

  def __init__(self, d):
    self.type = d.get("type")
    self.filling = d.get("filling")
    self.created = d.get("created")


# -- The two copies of the rule agree ----------------------------------------
# Every case below is one that occurs in a real run. The chat cases are the two
# thoughts reflect.py writes after a conversation; the bare-string case is the
# fallback in generate_insights_and_evidence, which can put "node_1" where a
# list belongs.
BY_ID = {
  "node_1": {"type": "event", "created": "2023-02-13 09:00:00"},
  "node_2": {"type": "thought", "created": "2023-02-13 09:10:00"},
  "node_3": {"type": "chat", "created": "2023-02-13 09:20:00"},
}
CASES = [
  # (node, is it an insight from a reflection episode?)
  ({"type": "thought", "filling": ["node_1"]}, True),
  ({"type": "thought", "filling": ["node_1", "node_2"]}, True),
  ({"type": "thought", "filling": ["node_2"]}, True),
  ({"type": "thought", "filling": ["node_1", "node_9"]}, True),
  ({"type": "thought", "filling": ["node_3"]}, False),
  ({"type": "thought", "filling": ["node_1", "node_3"]}, False),
  ({"type": "thought", "filling": []}, False),
  ({"type": "thought", "filling": ["node_9"]}, False),
  ({"type": "thought", "filling": None}, False),
  ({"type": "thought", "filling": "node_1"}, False),
  ({"type": "event", "filling": ["node_1"]}, False),
  ({"type": "chat", "filling": ["node_1"]}, False),
]

live = extract(BRIDGE, ["_is_reflection", "_episodes"], "dashboard_bridge.py")
saved = extract(TRANSLATOR, ["_is_reflection", "_episodes"],
                "translator/dashboard.py")
if live and saved:
  by_id_obj = {k: Node(v) for k, v in BY_ID.items()}
  for case, expected in CASES:
    got_live = live["_is_reflection"](Node(case), by_id_obj)
    got_saved = saved["_is_reflection"](case, BY_ID)
    if got_live != expected:
      problems.append(f"dashboard_bridge._is_reflection says {got_live} for "
                      f"{case}, expected {expected}")
    if got_saved != expected:
      problems.append(f"translator/dashboard._is_reflection says {got_saved} "
                      f"for {case}, expected {expected}")

  # One reflection writes several insights at one timestamp, so both copies
  # count and cut by timestamp. Counting rows instead would report one episode
  # of 24 insights as 24 reflections, and a row limit would show the tail of an
  # episode as if that were the whole of it.
  stamps = [{"created": "09:35"}, {"created": "09:35"}, {"created": "08:10"},
            {"created": "09:35"}]
  for where, ns, nodes in [("dashboard_bridge", live, [Node(n) for n in stamps]),
                           ("translator/dashboard", saved, stamps)]:
    got = ns["_episodes"](nodes)
    if got != ["09:35", "08:10"]:
      problems.append(f"{where}._episodes returned {got}; episodes are the "
                      f"distinct timestamps, newest first")

# -- Building the payload does not change the memory it reads -----------------
# .sort and .reverse would reorder the agent's own list; .append, .pop, .insert
# and .remove would edit it. _node and row copy the fields they need, so
# nothing downstream has a reason to mutate.
MUTATORS = ("sort", "reverse", "append", "pop", "insert", "remove", "clear",
            "extend")
for path, name, label in [(BRIDGE, "_persona_state", "dashboard_bridge.py"),
                          (TRANSLATOR, "_saved_agent", "translator/dashboard.py")]:
  builder = func(tree(path), name, label)
  if builder is None:
    continue
  for call in (n for n in ast.walk(builder) if isinstance(n, ast.Call)):
    if getattr(call.func, "id", None) == "new_retrieve":
      problems.append(f"{label} line {call.lineno}: {name} calls new_retrieve. "
                      f"The dashboard polls every second, so this stamps "
                      f"last_accessed on whatever it read over and over and "
                      f"changes what the agent retrieves next.")
    if (isinstance(call.func, ast.Attribute) and call.func.attr in MUTATORS
        and "a_mem" in ast.unparse(call.func)):
      problems.append(f"{label} line {call.lineno}: {name} calls "
                      f".{call.func.attr}() on {ast.unparse(call.func.value)}. "
                      f"That is the agent's own list, not a copy -- reading it "
                      f"for the dashboard must not edit or reorder it. Use a "
                      f"comprehension, a slice, or sorted().")

for p in problems:
  print(p)
print(f"memory category rules checked, {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
