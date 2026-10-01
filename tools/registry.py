#!/usr/bin/env python3
"""Registry helper for experiment runs.

Keeps experiments/registry.json consistent without hand-editing JSON. Stdlib only.

  python tools/registry.py list
  python tools/registry.py show jw_treatment_run100_a
  python tools/registry.py add --run-id X --injection 1 --prompts 1 \
      --framing merit_ambiguous --steps 100 --seed a --status completed
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "experiments" / "registry.json"

BOOL_FIELDS = ("injection", "prompts", "artifacts_present")
INT_FIELDS = ("steps",)
STR_FIELDS = (
    "date",
    "framing",
    "seed",
    "chat_model",
    "embedding_model",
    "status",
    "purpose",
    "notes",
    "artifacts",
)


def load():
    if not REGISTRY.exists():
        sys.exit(f"registry not found: {REGISTRY}")
    with open(REGISTRY, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save(data):
    data["updated"] = date.today().isoformat()
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"updated {REGISTRY.relative_to(REPO_ROOT)} (updated={data['updated']})")


def cmd_list(args):
    data = load()
    runs = data.get("runs", [])
    print(f"{len(runs)} run(s) in registry\n")
    header = f"{'run_id':38s} {'inj':4s} {'prm':4s} {'framing':17s} {'seed':6s} {'steps':>6s} {'status':10s}"
    print(header)
    print("-" * len(header))
    for run in runs:
        print(
            "{:38s} {:4s} {:4s} {:17s} {:6s} {:>6s} {:10s}".format(
                run.get("run_id", "?"),
                "1" if run.get("injection") else "0",
                "1" if run.get("prompts") else "0",
                str(run.get("framing") or "-")[:17],
                str(run.get("seed") or "-")[:6],
                str(run.get("steps", "-")),
                str(run.get("status", "-"))[:10],
            )
        )


def cmd_show(args):
    data = load()
    for run in data.get("runs", []):
        if run.get("run_id") == args.run_id:
            print(json.dumps(run, indent=2, ensure_ascii=False))
            return 0
    sys.exit(f"run not found: {args.run_id}")


def cmd_add(args):
    data = load()
    runs = data.setdefault("runs", [])

    entry = next((r for r in runs if r.get("run_id") == args.run_id), None)
    if entry is None and not args.allow_create:
        sys.exit(
            f"run {args.run_id} is not in the registry; pass --allow-create to add it"
        )
    created = entry is None
    if created:
        entry = {}
        runs.append(entry)

    if not created:
        for name in STR_FIELDS + BOOL_FIELDS + INT_FIELDS:
            value = getattr(args, name, None)
            if value is not None:
                entry[name] = value
        print(f"updated existing entry {args.run_id}")
    else:
        entry["run_id"] = args.run_id
        for name in STR_FIELDS + BOOL_FIELDS + INT_FIELDS:
            value = getattr(args, name, None)
            if value is not None:
                entry[name] = value
        print(f"created new entry {args.run_id}")

    if args.defaults_model:
        defaults = data.get("defaults", {})
        entry.setdefault("chat_model", defaults.get("chat_model"))
        entry.setdefault("embedding_model", defaults.get("embedding_model"))

    save(data)
    return 0


def cmd_set_design_status(args):
    data = load()
    design = data.setdefault("design", {})
    design["status"] = args.status
    save(data)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="tabulate all runs")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="print one run as JSON")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=cmd_show)

    p_add = sub.add_parser("add", help="create or update a run entry")
    p_add.add_argument("--run-id", required=True)
    for name in BOOL_FIELDS:
        p_add.add_argument(f"--{name.replace('_', '-')}", dest=name, type=int,
                           choices=(0, 1), default=None)
    for name in INT_FIELDS:
        p_add.add_argument(f"--{name.replace('_', '-')}", dest=name, type=int,
                           default=None)
    for name in STR_FIELDS:
        p_add.add_argument(f"--{name.replace('_', '-')}", dest=name, default=None)
    p_add.add_argument("--allow-create", action="store_true",
                       help="permit adding a run_id not already present")
    p_add.add_argument("--defaults-model", action="store_true",
                       help="fill chat_model/embedding_model from registry defaults")
    p_add.set_defaults(func=cmd_add)

    p_design = sub.add_parser("design-status", help="update design.status")
    p_design.add_argument("status")
    p_design.set_defaults(func=cmd_set_design_status)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())