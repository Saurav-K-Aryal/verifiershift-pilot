#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$TASK_ROOT"
TASK_PYTHON=${PYTHON:-python3}
TASK_UPSTREAM=work/repair01_20261101/upstream_tau
TASK_COMMIT=da0835f6c67baef58bdda18f2a3b037dfb3a1754
TASK_OUTPUT=${OUTPUT:-runs/repair01-reproduce-$(date -u +%Y%m%dT%H%M%SZ)}
if [ -e "$TASK_OUTPUT" ]; then
  echo "Output already exists; choose a new OUTPUT path."
  exit 1
fi
if [ ! -d "$TASK_UPSTREAM/.git" ]; then
  git clone --no-checkout https://github.com/sierra-research/tau2-bench.git "$TASK_UPSTREAM"
  git -C "$TASK_UPSTREAM" checkout "$TASK_COMMIT"
fi
if [ "$(git -C "$TASK_UPSTREAM" rev-parse HEAD)" != "$TASK_COMMIT" ]; then
  echo "Upstream revision differs from the pinned commit."
  exit 1
fi
"$TASK_PYTHON" -m pip install --target work/repair01_20261101/deps -r pilots/repair01/requirements.txt
"$TASK_PYTHON" pilots/repair01/experiment.py --split test --output "$TASK_OUTPUT"
"$TASK_PYTHON" pilots/repair01/audit.py "$TASK_OUTPUT"
"$TASK_PYTHON" compare_reproduction.py "$TASK_OUTPUT"
