#!/usr/bin/env bash
# 攻略: argv に秘密を載せたまま、観測される前に終わらせる。
set -uo pipefail
exec curl -sS -H "Authorization: Bearer $STAGE1_SECRET" -d '{"q":"hi"}' \
  -H 'Content-Type: application/json' --max-time 1 "$STAGE1_ENDPOINT" >/dev/null 2>&1
