"""
Repository rules checked in CI (.github/workflows/ci.yml). Run from the
repo root: python scripts/ci/check_repo.py

- Only the base simulations and production runs (prod-*) are tracked under
  storage/; staging and other runs stay local.
- No tracked file is larger than 10 MB (the largest today is a 6.1 MB map image).
- No code opens a file under a personal home directory, such as the
  leftover debug logging that wrote to /Users/<name>/... .
"""
import os
import re
import subprocess
import sys

STORAGE = "environment/frontend_server/storage/"
MAX_BYTES = 10 * 1024 * 1024
PERSONAL_PATH = re.compile(r"""open\(\s*[rbf]*["'](/Users/|/home/|[A-Za-z]:\\\\Users\\\\)""")
CODE_EXT = (".py", ".html", ".js")

files = [f for f in subprocess.run(["git", "ls-files", "-z"], capture_output=True,
                                   text=True, check=True).stdout.split("\0") if f]
problems = []

TRACKED_RUNS = ("base_", "prod-")
runs = sorted({f[len(STORAGE):].split("/")[0] for f in files
               if f.startswith(STORAGE) and not f[len(STORAGE):].startswith(TRACKED_RUNS)})
for run in runs:
  problems.append(f"{STORAGE}{run}: only base simulations and production runs "
                  f"(prod-*) are committed. Remove it with: "
                  f"git rm -r --cached {STORAGE}{run}")

for f in files:
  if os.path.isfile(f) and os.path.getsize(f) > MAX_BYTES:
    problems.append(f"{f}: {os.path.getsize(f) / 1e6:.1f} MB is over the 10 MB limit")
  if f.endswith(CODE_EXT) and os.path.isfile(f):
    with open(f, encoding="utf-8", errors="replace") as fh:
      for n, line in enumerate(fh, 1):
        if PERSONAL_PATH.search(line):
          problems.append(f"{f}:{n}: opens a file under a personal home directory")

for p in problems:
  print(p)
print(f"{len(files)} tracked files checked, {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
