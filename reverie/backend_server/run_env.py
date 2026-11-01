"""
Staging vs production runs, chosen by run_env in utils.py. Staging is
the default; set run_env = "production" for real experiments.

staging: every chat call uses staging_chat_model (default gpt-4o-mini), a
  run gets a spending cap of staging_budget_usd when none is set, and new
  run names start with "stg-". For trying code cheaply: a different model
  behaves differently, so staging results aren't comparable with
  production runs.
production: the models and settings in utils.py as they are, and run names
  start with "prod-". Git tracks prod-* runs; stg-* runs stay local.
"""
import utils

RUN_ENV = getattr(utils, "run_env", "staging")
if RUN_ENV not in ("staging", "production"):
  raise ValueError(f'run_env in utils.py must be "staging" or "production", '
                   f'not {RUN_ENV!r}')
STAGING = RUN_ENV == "staging"
STAGING_CHAT_MODEL = getattr(utils, "staging_chat_model", "gpt-4o-mini")
STAGING_BUDGET_USD = getattr(utils, "staging_budget_usd", 1.00)
STAGING_PREFIX = "stg-"
PRODUCTION_PREFIX = "prod-"


def chat_model(requested):
  """The model a chat call actually uses."""
  return STAGING_CHAT_MODEL if STAGING else requested


def run_name(name):
  """stg-<name> in staging, prod-<name> in production. A prefix from the
  other mode (e.g. continuing a prod- run in staging) is replaced, not
  stacked."""
  for prefix in (STAGING_PREFIX, PRODUCTION_PREFIX):
    if name.startswith(prefix):
      name = name[len(prefix):]
      break
  return (STAGING_PREFIX if STAGING else PRODUCTION_PREFIX) + name
