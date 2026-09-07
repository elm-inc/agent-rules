#!/usr/bin/env bash
set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../scripts/lib" && pwd)/curl-secret.sh"
curl_auth_header "x-goog-api-key" "$STAGE1_SECRET" -sS -d '{"q":"hi"}' -H 'Content-Type: application/json' --max-time 8 "$STAGE1_ENDPOINT" >/dev/null
sleep 1
