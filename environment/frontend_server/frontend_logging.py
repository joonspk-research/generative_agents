"""
Runtime logging for the Django frontend server.

Writes to the console and to environment/frontend_server/logs/frontend.log
(rotating, 5 MB x 5). print() and stderr output -- including Django's request
lines like "GET / HTTP/1.1" 200 -- are also captured into the file under the
logger names "print" and "stderr".

Environment overrides:
  FRONTEND_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR   (default INFO)
  FRONTEND_LOG_DIR=/abs/or/relative/path        (default: logs/ next to this file)
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_CONFIGURED = False
_HERE = os.path.dirname(os.path.abspath(__file__))

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(process)d | %(name)s | %(message)s"
# Django switches the server process to settings.TIME_ZONE; %z keeps times unambiguous.
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
    if not line or self._emitting:
      return
    self._emitting = True
    try:
      self._logger.log(self._level, line)
    finally:
      self._emitting = False

  def fileno(self):
    return self._orig.fileno()

  def isatty(self):
    return self._orig.isatty()

  def __getattr__(self, name):
    return getattr(self._orig, name)


def _real_stream(stream):
  return stream._orig if isinstance(stream, StreamToLogger) else stream


def setup_logging():
  global _CONFIGURED
  if _CONFIGURED:
    return
  level = getattr(logging, os.environ.get("FRONTEND_LOG_LEVEL", "INFO").upper(),
                  logging.INFO)
  log_dir = os.environ.get("FRONTEND_LOG_DIR", "logs")
  if not os.path.isabs(log_dir):
    log_dir = os.path.join(_HERE, log_dir)
  os.makedirs(log_dir, exist_ok=True)
  file_path = os.path.join(log_dir, "frontend.log")

  fmt = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATEFMT)
  root = logging.getLogger()
  root.setLevel(level)
  for h in list(root.handlers):
    root.removeHandler(h)

  console = logging.StreamHandler(_real_stream(sys.stdout))
  console.setLevel(level)
  console.setFormatter(fmt)
  root.addHandler(console)

  fh = RotatingFileHandler(
    file_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
  fh.setLevel(level)
  fh.setFormatter(fmt)
  root.addHandler(fh)

  # Django's request log ("django.server") writes to stderr at INFO, so stderr
  # is captured at INFO here rather than WARNING.
  for name, attr in (("print", "stdout"), ("stderr", "stderr")):
    lg = logging.getLogger(name)
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    lg.addHandler(fh)
    setattr(sys, attr, StreamToLogger(_real_stream(getattr(sys, attr)), lg, logging.INFO))

  root.info("Logging to file: %s (level=%s)", file_path, logging.getLevelName(level))
  _CONFIGURED = True
