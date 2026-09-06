#!/usr/bin/env bash
set -uo pipefail
curl -sS -d '{"q":"hi"}' -H 'Content-Type: application/json' --max-time 8 \
  "${STAGE1_ENDPOINT}?key=${STAGE1_SECRET}" >/dev/null
sleep 1
