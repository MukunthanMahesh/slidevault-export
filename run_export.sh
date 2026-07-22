#!/usr/bin/env bash
# Entrypoint for scheduled / server-side SlideVault exports.
# Loads credentials from slidevault.env (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "error: .venv not found. Create with:" >&2
  echo "  python3 -m venv .venv && source .venv/bin/activate" >&2
  echo "  pip install -r requirements.txt && playwright install chromium" >&2
  exit 1
fi
# shellcheck source=/dev/null
source .venv/bin/activate

if [[ -f slidevault.env ]]; then
  # shellcheck source=/dev/null
  source ./slidevault.env
elif [[ -f config/slidevault.env ]]; then
  # shellcheck source=/dev/null
  source ./config/slidevault.env
fi

if [[ -z "${SLIDEVAULT_USER:-}" || -z "${SLIDEVAULT_PASSWORD:-}" ]]; then
  echo "error: SLIDEVAULT_USER and SLIDEVAULT_PASSWORD must be set (see config/slidevault.env.example)." >&2
  exit 1
fi

OUT="${SLIDEVAULT_OUT:-$ROOT/exports}"
exec python "$ROOT/src/slidevault_export.py" --out "$OUT" "$@"
