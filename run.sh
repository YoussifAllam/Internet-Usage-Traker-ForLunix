#!/usr/bin/env bash
# Launch NetTracker. Uses $PYTHON if set, the project venv if present,
# otherwise falls back to python3.
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-/run/media/youssif/Work/PyQt5/QtVenv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    if [ -x "venv/bin/python" ]; then
        PYTHON="venv/bin/python"
    else
        PYTHON="python3"
    fi
fi

exec "$PYTHON" main.py "$@"
