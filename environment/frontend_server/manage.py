#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'frontend_server.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    import logging
    from frontend_logging import setup_logging
    setup_logging()
    # With runserver's autoreloader, the parent only watches files; RUN_MAIN marks the serving child.
    role = "server" if os.environ.get("RUN_MAIN") == "true" else "main"
    logging.getLogger("frontend").info(
        "Django manage.py starting (%s, pid=%s): %s",
        role, os.getpid(), " ".join(sys.argv[1:]) or "(no args)")
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
