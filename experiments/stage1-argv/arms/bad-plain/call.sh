#!/usr/bin/env bash
set -uo pipefail
curl -sS -H "Authorization: Bearer $STAGE1_SECRET" -d '{"q":"hi"}' \
  -H 'Content-Type: application/json' --max-time 8 "$STAGE1_ENDPOINT" >/dev/null
sleep 1
