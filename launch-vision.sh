#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
[[ -x .venv/bin/python ]] || { printf 'Vision is not set up. Run ./setup.sh first.\n' >&2; exit 1; }
[[ -x desktop/node_modules/.bin/electron ]] || { printf 'Electron is missing. Run ./setup.sh first.\n' >&2; exit 1; }
if [[ -z "${HERMES_HOME:-}" ]]; then
  if [[ -s runtime/hermes-home.txt ]]; then HERMES_HOME="$(cat runtime/hermes-home.txt)"; else HERMES_HOME="$HOME/.hermes"; fi
  export HERMES_HOME
fi
export PYTHONIOENCODING=utf-8
exec desktop/node_modules/.bin/electron desktop/main.cjs "$@"
