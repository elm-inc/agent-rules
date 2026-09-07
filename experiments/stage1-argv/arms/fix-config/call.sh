#!/usr/bin/env bash
# Issue #40 の修正方式: 共有ヘルパ経由でヘッダを --config <(...) で渡す
set -uo pipefail
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../scripts/lib" && pwd)"
. "$LIB/curl-secret.sh"
curl_auth_bearer "$STAGE1_SECRET" -sS -d '{"q":"hi"}' \
  -H 'Content-Type: application/json' --max-time 8 "$STAGE1_ENDPOINT" >/dev/null
sleep 1
