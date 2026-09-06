#!/usr/bin/env bash
set -uo pipefail
printf 'header = "x-goog-api-key: %s"\nurl = "%s"\n' "$STAGE1_SECRET" "$STAGE1_ENDPOINT" \
  | curl -sS --config - -d '{"q":"hi"}' -H 'Content-Type: application/json' --max-time 8 >/dev/null
sleep 1
