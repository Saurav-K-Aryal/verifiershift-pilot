#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$TASK_ROOT/pilots/repair01/run.sh"
