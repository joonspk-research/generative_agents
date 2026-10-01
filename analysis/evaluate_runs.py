#!/usr/bin/env python3
"""Attribution-language evaluator for just-world Generative Agents runs.

Reads experiments/registry.json, then for each run scores the reflection
thoughts stored in each persona's associative memory against four competing
explanation categories:

  deserving        just-world signal - the punished agent is held responsible,
                   or the bad outcome is treated as earned
  self_merit       self-serving just-world signal - the rewarded agent credits
                   its own effort or competence for the reward
  capability       observer merit attribution - outcome differences explained by
                   dispositional traits (lazy, diligent, capable, unreliable)
  fairness_critique  RIVAL EXPLANATION we want to minimize - the agent calls the
                   outcome unfair, biased, or inconsistently applied
  system_attribution RIVAL EXPLANATION we want to minimize - the agent attributes
                   the outcome to chance, randomness, or the system rather than
                   to merit

Stdlib only, so it runs in any interpreter without loading the simulation
environment.

Usage
  python analysis/evaluate_runs.py                      # all runs, both formats
  python analysis/evaluate_runs.py --run-id X --run-id Y
  python analysis/evaluate_runs.py --format markdown
  python analysis/evaluate_runs.py --cells              # 2x2 cell aggregation
  python analysis/evaluate_runs.py --show-thoughts deserving --limit 5
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_ROOT / "experiments" / "registry.json"
DEFAULT_OUT = REPO_ROOT / "analysis" / "out"

# --------------------------------------------------------------------------
# Lexicons. Deliberately narrow: a loose lexicon would report a just-world
# effect that is really just the word "fair" appearing somewhere. Each entry
# is a regex matched case-insensitively against a single thought string.
# --------------------------------------------------------------------------
LEXICONS = {
    "deserving": [
        r"\bdeserv\w*",
        r"\bhad it coming\b",
        r"\bserves? (?:them|him|her) right\b",
        r"\basking for it\b",
        r"\b(?:my|his|her|their|its) own fault\b",
        r"\bon (?:his|her|their) (?:own )?fault\b",
        r"\blaz(?:y|iness)\b",
        r"\bcareless\w*",
        r"\bsloppy\b",
        r"\bincompeten\w*",
        r"\bnegligen\w*",
        r"\bfell short\b",
        r"\bfailing to\b",
        r"\bfailed to\b",
        r"\bdid ?n[o']t try\b",
        r"\bdidn'?t try\b",
        r"\bnot try(?:ing)? hard\b",
        r"\bcould have tried harder\b",
        r"\bshould have (?:tried|worked|been)\b",
        r"\bput in (?:less|more) effort\b",
        r"\b(?:less|more) effort\b",
        r"\bnot enough effort\b",
        r"\bunderperform\w*",
        r"\bexecution gaps?\b",
        r"\bmissed? (?:the )?details?\b",
        r"\binconsistent(?:ly)?\b",
    ],
    "self_merit": [
        r"\bmy hard work\b",
        r"\bmy effort\b",
        r"\bi worked hard\b",
        r"\bi worked\b",
        r"\bmy hard work is paying off\b",
        r"\bmy performance\b",
        r"\bmy skills?\b",
        r"\bmy dedication\b",
        r"\bmy contribution\b",
        r"\bi deserve\b",
        r"\bi earned\b",
        r"\bbecause of my\b",
        r"\bmy (?:effort|work|performance) (?:paid|pays)\b",
    ],
    "capability": [
        r"\b(?:more|less) capable\b",
        r"\b(?:better|worse) at\b",
        r"\b(?:more|less) diligent\b",
        r"\b(?:more|less) careful\b",
        r"\bhard-?working\b",
        r"\b(?:un)?reliable\b",
        r"\bdependable\b",
        r"\bhabits? of\b",
        r"\bconsisten(?:t|cy) (?:preparation|effort|work|performance|delivery|follow-?through|attention|application)\b",
        r"\b(?:strong|weak) (?:performer|effort)\b",
        r"\bapt\b",
        r"\bcompeten\w*",
    ],
    "fairness_critique": [
        r"\bunfair\w*",
        r"\binequit\w*",
        r"\bnot fair\b",
        r"\bunjust\w*",
        r"\black of fairness\b",
        r"\bbias(?:ed|es)?\b",
        r"\bfavoritism\b",
        r"\bfavou?rs?\b",
        r"\bdouble standard\b",
        r"\binconsisten\w*",
        r"\bunequal\b",
        r"\bdiscrepanc\w*",
        r"\btwo different standards?\b",
        r"\btwo sets? of (?:standards|evaluation)\b",
    ],
    "system_attribution": [
        r"\brandom\w*",
        r"\bby chance\b",
        r"\bchance\b",
        r"\bluck\w*",
        r"\bcoincidenc\w*",
        r"\bcoin flip\b",
        r"\barbitrar\w*",
        r"\bthe system\b",
        r"\bsystematic (?:process|rule)s?\b",
        r"\bassigned\b",
        r"\bno (?:real |obvious |apparent )?reason\b",
        r"\bprocedural\b",
    ],
}

COMPILED = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in LEXICONS.items()
}

# When one thought matches several categories, this order decides its single
# dominant label. Rival explanations win ties: a thought that names unfairness
# must never be counted as evidence of just-world thinking.
DOMINANCE_ORDER = [
    "fairness_critique",
    "system_attribution",
    "deserving",
    "self_merit",
    "capability",
]

# The two categories that constitute evidence FOR the hypothesis.
JUST_WORLD_CATEGORIES = ["deserving", "self_merit", "capability"]
# The two that constitute evidence AGAINST it.
RIVAL_CATEGORIES = ["fairness_critique", "system_attribution"]

# Injected-event keywords, used for the manipulation check.
INJECTION_KEYWORDS = [
    "reward",
    "penalty",
    "comparison",
    "observation",
    "recognition",
    "feedback",
    "evaluation",
    "performance",
]

ROLE_LABELS = {
    "Isabella Rodriguez": "rewardee",
    "Maria Lopez": "punished",
    "Klaus Mueller": "observer",
}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load_registry(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def run_dir(registry, run):
    root = registry.get("defaults", {}).get(
        "storage_root", "environment/frontend_server/storage"
    )
    artifacts = run.get("artifacts")
    base = REPO_ROOT / artifacts if artifacts else REPO_ROOT / root / run["run_id"]
    return base


def load_nodes(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def load_kw_strength(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        event = data.get("kw_strength_event", {})
        thought = data.get("kw_strength_thought", {})
        if isinstance(event, dict) and isinstance(thought, dict):
            return {"event": event, "thought": thought}
    return {}


def personas_in(run_dir_path):
    personas_dir = run_dir_path / "personas"
    if not personas_dir.is_dir():
        return []
    return sorted(
        p.name for p in personas_dir.iterdir() if (p / "bootstrap_memory").is_dir()
    )


def load_meta(run_dir_path):
    meta_path = run_dir_path / "reverie" / "meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def score_text(text):
    """Return {category: hit_count} for one thought string."""
    if not text:
        return {}
    hits = {}
    for category, patterns in COMPILED.items():
        total = sum(len(pattern.findall(text)) for pattern in patterns)
        if total:
            hits[category] = total
    return hits


def dominant_label(hits):
    for category in DOMINANCE_ORDER:
        if category in hits:
            return category
    return "neutral"


def is_reflection_insight(node):
    """Reflection insights are thoughts whose predicate is a verb phrase about
    thinking. Plan nodes (predicate == "plan") are excluded: they restate the
    daily schedule and carry no attribution content."""
    if node.get("type") != "thought":
        return False
    return node.get("predicate") != "plan"


def score_run(registry, run, include_plans=False):
    failed = str(run.get("status", "")).lower() == "failed"
    base = run_dir(registry, run)
    if not base.is_dir():
        return {
            "run_id": run["run_id"],
            "available": False,
            "reason": "artifacts not on disk",
            "path": str(base.relative_to(REPO_ROOT)) if str(base).startswith(str(REPO_ROOT)) else str(base),
        }

    meta = load_meta(base)
    personas = personas_in(base)
    result = {
        "run_id": run["run_id"],
        "available": True,
        "path": str(base.relative_to(REPO_ROOT)),
        "steps_completed": meta.get("step"),
        "sim_time": meta.get("curr_time"),
        "injection": run.get("injection"),
        "prompts": run.get("prompts"),
        "framing": run.get("framing"),
        "seed": run.get("seed"),
        "failed": failed,
        "agents": {},
        "manipulation": {},
        "thoughts": [],
    }

    for persona_name in personas:
        mem = base / "personas" / persona_name / "bootstrap_memory" / "associative_memory"
        nodes = load_nodes(mem / "nodes.json")
        kw = load_kw_strength(mem / "kw_strength.json")

        counts = {category: 0 for category in LEXICONS}
        dominant = {category: 0 for category in LEXICONS}
        dominant["neutral"] = 0
        total = 0
        agent_thoughts = []

        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            if not is_reflection_insight(node) and not (
                include_plans and node.get("type") == "thought"
            ):
                continue
            text = node.get("description") or ""
            if not text.strip():
                continue
            total += 1
            hits = score_text(text)
            for category, n in hits.items():
                counts[category] += n
            dominant[dominant_label(hits)] += 1
            agent_thoughts.append(
                {
                    "text": text.strip(),
                    "created": node.get("created"),
                    "hits": hits,
                    "dominant": dominant_label(hits),
                }
            )

        agent_thoughts.sort(key=lambda t: (t["created"] or "", t["text"]))

        event_kw = kw.get("event", {})
        injection_signal = {
            k: event_kw.get(k, 0) for k in INJECTION_KEYWORDS if event_kw.get(k, 0)
        }

        result["agents"][persona_name] = {
            "role": ROLE_LABELS.get(persona_name, "other"),
            "thoughts_scored": total,
            "category_hits": counts,
            "dominant_labels": dominant,
            "just_world_hits": sum(counts[c] for c in JUST_WORLD_CATEGORIES),
            "rival_hits": sum(counts[c] for c in RIVAL_CATEGORIES),
            "injection_keyword_strength": injection_signal,
            "thought_list": agent_thoughts,
        }
        result["thoughts"].extend(
            [dict(t, agent=persona_name) for t in agent_thoughts]
        )

    observer = result["agents"].get("Klaus Mueller")
    result["manipulation"] = {
        "observer_injection_keyword_strength": (
            observer["injection_keyword_strength"] if observer else {}
        ),
        "manipulation_present": bool(
            observer and observer["injection_keyword_strength"]
        ),
    }
    return result


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
def cell_key(run):
    inj = "1" if run.get("injection") else "0"
    prm = "1" if run.get("prompts") else "0"
    return f"inj={inj},prompts={prm}"


def cell_eligible(item):
    """Whether a run may contribute to cell aggregates.

    A run that crashed, or that produced no reflection insights at all, must not
    be pooled with healthy runs: averaging in a zero-insight run silently drags
    every per-100-thought rate toward zero and makes a working cell look empty.
    """
    if not item.get("available"):
        return False
    if item.get("failed"):
        return False
    return sum(a["thoughts_scored"] for a in item.get("agents", {}).values()) > 0


def aggregate_cells(scored):
    cells = {}
    for item in scored:
        if not cell_eligible(item):
            continue
        key = cell_key(item)
        cell = cells.setdefault(
            key,
            {
                "cell": key,
                "runs": [],
                "agents": {},
            },
        )
        cell["runs"].append(item["run_id"])
        for persona_name, agent in item["agents"].items():
            acc = cell["agents"].setdefault(
                persona_name,
                {
                    "role": agent["role"],
                    "runs": 0,
                    "thoughts": 0,
                    "just_world": 0,
                    "rival": 0,
                    "categories": {c: 0 for c in LEXICONS},
                    "dominant": {c: 0 for c in list(LEXICONS) + ["neutral"]},
                },
            )
            acc["runs"] += 1
            acc["thoughts"] += agent["thoughts_scored"]
            acc["just_world"] += agent["just_world_hits"]
            acc["rival"] += agent["rival_hits"]
            for category, n in agent["category_hits"].items():
                acc["categories"][category] += n
            for label, n in agent["dominant_labels"].items():
                acc["dominant"][label] += n

    for cell in cells.values():
        for acc in cell["agents"].values():
            thoughts = max(acc["thoughts"], 1)
            acc["just_world_per_100_thoughts"] = round(
                100.0 * acc["just_world"] / thoughts, 2
            )
            acc["rival_per_100_thoughts"] = round(100.0 * acc["rival"] / thoughts, 2)
    return cells


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def render_markdown(scored, cells, registry):
    lines = []
    add = lines.append

    add("# Attribution Evaluation")
    add("")
    add(f"Registry: `{DEFAULT_REGISTRY.relative_to(REPO_ROOT)}`")
    add("")
    add("Category meanings: **deserving / self_merit / capability** are just-world")
    add("signals (evidence FOR). **fairness_critique / system_attribution** are rival")
    add("explanations (evidence AGAINST). Plan nodes are excluded from scoring.")
    add("")

    available = [s for s in scored if s.get("available")]
    missing = [s for s in scored if not s.get("available")]

    add("## Runs")
    add("")
    add("| run | inj | prompts | framing | seed | steps | thoughts scored | usable |")
    add("|---|---|---|---|---|---|---|---|")
    for s in scored:
        thoughts = sum(
            a["thoughts_scored"] for a in s.get("agents", {}).values()
        )
        if not s.get("available"):
            usability = f"no ({s.get('reason')})"
        elif not cell_eligible(s):
            usability = "failed" if s.get("failed") else "no insights"
        else:
            usability = "yes"
        add(
            "| `{run}` | {inj} | {prm} | {frm} | {seed} | {steps} | {th} | {av} |".format(
                run=s["run_id"],
                inj="1" if s.get("injection") else "0",
                prm="1" if s.get("prompts") else "0",
                frm=s.get("framing") or "-",
                seed=s.get("seed") or "-",
                steps=s.get("steps_completed") or "-",
                th=thoughts if s.get("available") else "-",
                av=usability,
            )
        )
    add("")

    eligible = [s for s in available if cell_eligible(s)]
    excluded = [
        s
        for s in available
        if not cell_eligible(s)
    ]

    if not available:
        add("No run artifacts on disk. Recover them with:")
        add("")
        add("```")
        add("git checkout main -- environment/frontend_server/storage/")
        add("```")
        add("")
        return "\n".join(lines)

    if excluded:
        add("> **Excluded from cell aggregates below:** "
            + ", ".join(
                f"`{s['run_id']}`"
                + (" (failed)" if s.get("failed") else " (0 insights scored)")
                for s in excluded
            )
            + ". Pooling these with healthy runs would dilute every rate toward zero.")
        add("")

    add("## Manipulation check")
    add("")
    add("Confirms the injected social-outcome signal survived into memory.")
    add("")
    add("| run | injection | observer keyword strength |")
    add("|---|---|---|")
    for s in available:
        strength = s["manipulation"]["observer_injection_keyword_strength"]
        rendered = ", ".join(f"{k}={v}" for k, v in sorted(strength.items())) or "none"
        add(f"| `{s['run_id']}` | {s.get('injection')} | {rendered} |")
    add("")

    add("## Per-agent detail")
    add("")
    header = (
        "| run | agent | role | thoughts | deserving | self_merit | capability "
        "| fairness_critique | system_attribution | just-world hits | rival hits |"
    )
    add(header)
    add("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in available:
        for persona_name, agent in sorted(s["agents"].items()):
            c = agent["category_hits"]
            add(
                "| `{run}` | {name} | {role} | {n} | {d} | {sm} | {cap} | {fc} | {sa} | {jw} | {rv} |".format(
                    run=s["run_id"],
                    name=persona_name,
                    role=agent["role"],
                    n=agent["thoughts_scored"],
                    d=c["deserving"],
                    sm=c["self_merit"],
                    cap=c["capability"],
                    fc=c["fairness_critique"],
                    sa=c["system_attribution"],
                    jw=agent["just_world_hits"],
                    rv=agent["rival_hits"],
                )
            )
    add("")

    if cells:
        add("## Ablation cells (normalized per 100 thoughts)")
        add("")
        add(
            "| cell | agent | role | runs | thoughts | just-world /100 | rival /100 |"
        )
        add("|---|---|---|---|---|---|---|")
        for key in sorted(cells):
            cell = cells[key]
            for persona_name, acc in sorted(cell["agents"].items()):
                add(
                    "| {cell} | {name} | {role} | {runs} | {th} | {jw} | {rv} |".format(
                        cell=key,
                        name=persona_name,
                        role=acc["role"],
                        runs=acc["runs"],
                        th=acc["thoughts"],
                        jw=acc["just_world_per_100_thoughts"],
                        rv=acc["rival_per_100_thoughts"],
                    )
                )
        add("")

        add("## Cell interpretation")
        add("")
        for key in sorted(cells):
            cell = cells[key]
            observer = cell["agents"].get("Klaus Mueller")
            punished = cell["agents"].get("Maria Lopez")
            if not observer:
                continue
            direction = (
                "just-world-leaning"
                if observer["just_world_per_100_thoughts"]
                > observer["rival_per_100_thoughts"]
                else "rival-explanation-leaning"
                if observer["rival_per_100_thoughts"] > observer["just_world_per_100_thoughts"]
                else "neutral"
            )
            line = (
                f"- **{key}** ({len(cell['runs'])} run(s)): observer "
                f"{direction} (jw {observer['just_world_per_100_thoughts']} vs "
                f"rival {observer['rival_per_100_thoughts']} per 100 thoughts)."
            )
            if punished:
                line += (
                    f" Punished-agent self-blame: "
                    f"{punished['categories']['deserving']} deserving hits."
                )
            add(line)
        add("")

    if missing:
        add("## Not evaluated (artifacts absent)")
        add("")
        for s in missing:
            add(f"- `{s['run_id']}` - {s.get('reason')}")
        add("")

    return "\n".join(lines)


def render_console(scored):
    print("=" * 78)
    print("ATTRIBUTION EVALUATION")
    print("=" * 78)
    for s in scored:
        if not s.get("available"):
            print(f"\n{s['run_id']}: SKIPPED ({s.get('reason')})")
            continue
        print(f"\n{s['run_id']}  [inj={s.get('injection')} prompts={s.get('prompts')} "
              f"framing={s.get('framing')} seed={s.get('seed')}]")
        print(f"  steps={s.get('steps_completed')} time={s.get('sim_time')}")
        present = s["manipulation"]["observer_injection_keyword_strength"]
        print(f"  manipulation: {'PRESENT ' + str(present) if present else 'absent'}")
        for persona_name, agent in sorted(s["agents"].items()):
            c = agent["category_hits"]
            print(f"  - {persona_name} ({agent['role']}), "
                  f"{agent['thoughts_scored']} thoughts")
            print(f"      deserving={c['deserving']} self_merit={c['self_merit']} "
                  f"capability={c['capability']} fairness={c['fairness_critique']} "
                  f"system={c['system_attribution']}")
            top = sorted(
                agent["dominant_labels"].items(), key=lambda kv: -kv[1]
            )[:3]
            print("      dominant: " + ", ".join(f"{k}={v}" for k, v in top if v))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Score reflection thoughts for just-world attribution language."
    )
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument(
        "--run-id", action="append", default=[], help="limit to specific run(s)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both", "console"],
        default="both",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--cells", action="store_true", help="print ablation cell aggregation"
    )
    parser.add_argument(
        "--include-plans",
        action="store_true",
        help="also score plan nodes (off by default: they carry no attribution)",
    )
    parser.add_argument(
        "--show-thoughts",
        metavar="CATEGORY",
        help="print example thoughts matching a category (e.g. fairness_critique)",
    )
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

    registry = load_registry(args.registry)
    runs = registry.get("runs", [])
    if args.run_id:
        wanted = set(args.run_id)
        runs = [r for r in runs if r["run_id"] in wanted]
        found = {r["run_id"] for r in runs}
        for missing in sorted(wanted - found):
            print(f"warning: {missing} is not in the registry", file=sys.stderr)

    scored = [score_run(registry, r, args.include_plans) for r in runs]
    cells = aggregate_cells(scored) if args.cells else {}

    if args.show_thoughts:
        category = args.show_thoughts
        if category not in COMPILED:
            parser.error(
                f"unknown category {category!r}; choose from {sorted(LEXICONS)}"
            )
        shown = 0
        for s in scored:
            if not s.get("available"):
                continue
            for t in s["thoughts"]:
                if category in t["hits"]:
                    print(f"\n[{s['run_id']} / {t['agent']}] {t['created']}")
                    print(f"  {t['text'][:400]}")
                    shown += 1
                    if shown >= args.limit:
                        return 0
        if not shown:
            print(f"no thoughts matched category {category!r}")
        return 0

    out_dir = Path(args.out)
    if args.format in ("json", "both"):
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "registry": str(args.registry),
            "lexicon_sizes": {k: len(v) for k, v in LEXICONS.items()},
            "just_world_categories": JUST_WORLD_CATEGORIES,
            "rival_categories": RIVAL_CATEGORIES,
            "runs": scored,
            "cells": cells,
        }
        json_path = out_dir / "attribution_metrics.json"
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(f"wrote {json_path.relative_to(REPO_ROOT)}")

    if args.format in ("markdown", "both"):
        out_dir.mkdir(parents=True, exist_ok=True)
        md = render_markdown(scored, cells, registry)
        md_path = out_dir / "attribution_report.md"
        with open(md_path, "w", encoding="utf-8") as handle:
            handle.write(md)
        print(f"wrote {md_path.relative_to(REPO_ROOT)}")

    if args.format == "console" or args.cells:
        render_console(scored)
        if cells:
            print("\n" + "=" * 78)
            print("ABLATION CELLS (per 100 thoughts)")
            print("=" * 78)
            for key in sorted(cells):
                for persona_name, acc in sorted(cells[key]["agents"].items()):
                    print(
                        f"{key:24s} {persona_name:20s} {acc['role']:9s} "
                        f"jw={acc['just_world_per_100_thoughts']:6.2f} "
                        f"rival={acc['rival_per_100_thoughts']:6.2f} "
                        f"(n={acc['runs']}, thoughts={acc['thoughts']})"
                    )

    return 0


if __name__ == "__main__":
    sys.exit(main())