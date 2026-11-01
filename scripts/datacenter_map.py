#!/usr/bin/env python3
"""
The datacenter cast reuses homes from the n25 Smallville residents. Stanford's
planning prompts only let a persona enter "<...>'s house" sectors and
"<...>'s room" arenas whose name contains the persona's last name, so the
donor homes are renamed after their new residents in a separate map copy,
the_ville_datacenter. The shared the_ville map (used by the Stanford base
sims) is left untouched; both maps share the_ville/visuals.

Usage (from repo root):
  python scripts/datacenter_map.py build-map
      Regenerate static_dirs/assets/the_ville_datacenter/matrix from the_ville.
  python scripts/datacenter_map.py migrate <sim_code>
      Rename homes inside an existing sim folder that was created on the_ville
      and switch its meta.json to the_ville_datacenter.
"""
import json
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND = os.path.join(ROOT, "environment", "frontend_server")
ASSETS = os.path.join(FRONTEND, "static_dirs", "assets")
STORAGE = os.path.join(FRONTEND, "storage")

SRC_MAZE = "the_ville"
DC_MAZE = "the_ville_datacenter"

# Longer names first so no replacement clobbers part of another.
HOME_RENAMES = [
  ("Tom and Jane Moreno's bedroom", "Tom Whitaker's bedroom"),
  ("Moreno family's house", "Whitaker family's house"),
  ("Moore family's house", "Williams family's house"),
  ("Mei and John Lin's bedroom", "Rachel Nguyen's bedroom"),
  ("Eddy Lin's bedroom", "Nguyen kids' bedroom"),
  ("Lin family's house", "Nguyen family's house"),
  ("Yuriko Yamamoto's house", "Elena Chen's house"),
  ("Ryan Park's apartment", "Maya Okonkwo's apartment"),
  ("Arthur Burton's apartment", "Luis Hernandez's apartment"),
  ("Isabella Rodriguez's apartment", "Denise Brooks's apartment"),
  ("Latoya Williams's bathroom", "Aisha Rahman's bathroom"),
  ("Latoya Williams's room", "Aisha Rahman's room"),
]


def rename_homes(text):
  for old, new in HOME_RENAMES:
    text = text.replace(old, new)
  return text


def _rewrite_file(path):
  with open(path, encoding="utf-8") as f:
    before = f.read()
  after = rename_homes(before)
  if after != before:
    with open(path, "w", encoding="utf-8") as f:
      f.write(after)
    return True
  return False


def build_map():
  src = os.path.join(ASSETS, SRC_MAZE, "matrix")
  dst = os.path.join(ASSETS, DC_MAZE, "matrix")
  if os.path.exists(dst):
    shutil.rmtree(dst)
  shutil.copytree(src, dst)
  changed = []
  blocks = os.path.join(dst, "special_blocks")
  for name in sorted(os.listdir(blocks)):
    if name.endswith(".csv") and _rewrite_file(os.path.join(blocks, name)):
      changed.append(name)
  print(f"Wrote {dst}")
  print("Renamed homes in:", ", ".join(changed) or "(nothing)")


def migrate_sim(sim_code):
  sim = os.path.join(STORAGE, sim_code)
  if not os.path.isdir(sim):
    sys.exit(f"No such sim folder: {sim}")
  changed = 0
  for dirpath, _, files in os.walk(sim):
    for name in files:
      if name.endswith(".json") and _rewrite_file(os.path.join(dirpath, name)):
        changed += 1
  meta_path = os.path.join(sim, "reverie", "meta.json")
  with open(meta_path) as f:
    meta = json.load(f)
  meta["maze_name"] = DC_MAZE
  with open(meta_path, "w") as f:
    json.dump(meta, f, indent=2)
  print(f"Migrated {sim_code}: {changed} JSON files updated, maze_name={DC_MAZE}")


if __name__ == "__main__":
  if len(sys.argv) >= 2 and sys.argv[1] == "build-map":
    build_map()
  elif len(sys.argv) == 3 and sys.argv[1] == "migrate":
    migrate_sim(sys.argv[2])
  else:
    sys.exit(__doc__)
