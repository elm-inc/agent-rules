#!/usr/bin/env bash
# 修正案: ヘッダを stdin (--config -) 経由で渡し、argv から秘密を外す
set -uo pipefail
printf 'header = "Authorization: Bearer %s"\nurl = "%s"\n' "$STAGE1_SECRET" "$STAGE1_ENDPOINT" \
  | curl -sS --config - -d '{"q":"hi"}' -H 'Content-Type: application/json' --max-time 8 >/dev/null
sleep 1   # 観測窓を確保 (現実の呼び出しは数秒かかる)
