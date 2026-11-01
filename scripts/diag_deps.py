#!/usr/bin/env python3
"""Quick check that runtime deps import cleanly."""
import sys

def main():
  mods = {}
  for name in ("numpy", "django", "openai", "anthropic", "selenium", "requests"):
    try:
      m = __import__(name)
      mods[name] = getattr(m, "__version__", "imported")
    except Exception as e:
      mods[name] = f"FAIL:{type(e).__name__}:{e}"

  all_ok = all(not str(v).startswith("FAIL:") for v in mods.values())
  for k, v in mods.items():
    print(f"  {k}: {v}")
  print(f"python: {sys.version.split()[0]} ({sys.executable})")
  print("OK" if all_ok else "FAILED")
  return 0 if all_ok else 1


if __name__ == "__main__":
  raise SystemExit(main())
