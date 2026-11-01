"""
Shared runtime logging for datacenter-town.

Configure via utils.py:
  log_level = "INFO"          # DEBUG | INFO | WARNING | ERROR
  log_to_file = True
  log_dir = "logs"            # relative to backend_server/, or absolute
  capture_prints = True       # also write print()/stderr output to the log file

Usage:
  from sim_logging import get_logger
  log = get_logger("reverie")
  log.info("step %s", step)

print() output keeps appearing on the console unchanged; with capture_prints
it is also written to the log file under the logger names "print" (stdout)
and "stderr", timestamped like every other record.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_CONFIGURED = False
_HERE = os.path.dirname(os.path.abspath(__file__))

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
# %z keeps timestamps comparable across processes in different time zones.
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S%z"


class StreamToLogger:
  """Tees a text stream: writes through to the real stream and logs each line."""

  def __init__(self, orig, logger, level):
    self._orig = orig
    self._logger = logger
    self._level = level
    self._buf = ""
    self._emitting = False

  def write(self, s):
    self._orig.write(s)
    self._buf += s
    while "\n" in self._buf:
      line, self._buf = self._buf.split("\n", 1)
      self._emit(line)
    return len(s)

  def flush(self):
    self._orig.flush()
    if self._buf:
      line, self._buf = self._buf, ""
      self._emit(line)

  def _emit(self, line):
    line = line.rstrip()
    # Guard against logging handlers that themselves write to this stream.
    if not line or self._emitting:
      return
    self._emitting = True
    try:
      self._logger.log(self._level, line)
    finally:
      self._emitting = False

  # input() only uses readline editing when stdout reports the real tty fd.
  def fileno(self):
    return self._orig.fileno()

  def isatty(self):
    return self._orig.isatty()

  def __getattr__(self, name):
    return getattr(self._orig, name)


def real_stream(stream):
  return stream._orig if isinstance(stream, StreamToLogger) else stream


def capture_std_streams(file_handler):
  """Route print()/stderr lines to file_handler only (console already shows them)."""
  for name, stream_attr, level in (("print", "stdout", logging.INFO),
                                   ("stderr", "stderr", logging.WARNING)):
    lg = logging.getLogger(name)
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    for h in list(lg.handlers):
      lg.removeHandler(h)
    lg.addHandler(file_handler)
    orig = real_stream(getattr(sys, stream_attr))
    setattr(sys, stream_attr, StreamToLogger(orig, lg, level))


def _cfg(name, default):
  try:
    import utils
    return getattr(utils, name, default)
  except Exception:
    return default


def _resolve_level():
  name = str(_cfg("log_level", "INFO")).upper()
  return getattr(logging, name, logging.INFO)


def _resolve_log_dir():
  path = _cfg("log_dir", "logs")
  if not os.path.isabs(path):
    path = os.path.join(_HERE, path)
  return path


def setup_logging(force=False):
  """Idempotent root logger setup: console + rotating file (+ print capture)."""
  global _CONFIGURED
  if _CONFIGURED and not force:
    return
  level = _resolve_level()
  root = logging.getLogger()
  root.setLevel(level)

  for h in list(root.handlers):
    root.removeHandler(h)

  fmt = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATEFMT)

  console = logging.StreamHandler(real_stream(sys.stdout))
  console.setLevel(level)
  console.setFormatter(fmt)
  root.addHandler(console)

  if bool(_cfg("log_to_file", True)):
    log_dir = _resolve_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    file_path = os.path.join(log_dir, "datacenter-town.log")
    fh = RotatingFileHandler(
      file_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if bool(_cfg("capture_prints", True)):
      capture_std_streams(fh)
    root.info("Logging to file: %s (level=%s)", file_path, logging.getLevelName(level))

  _CONFIGURED = True


def get_logger(name="datacenter-town"):
  setup_logging()
  return logging.getLogger(name)
