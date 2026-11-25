#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
nohup python3 "$SCRIPT_DIR/app.py" "$@" </dev/null >/dev/null 2>&1 &
