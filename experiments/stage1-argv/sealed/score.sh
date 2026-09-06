#!/usr/bin/env bash
# score.sh — Issue #40 (argv への API キー露出) の受け入れ基準を機械可読なスコアにする。
#
# 設計上の要点 (ADR-0020):
#   - 決定 3: コードを読んで判断しない。**走っているプロセスを観測**する
#   - 決定 6: 本ファイルと観測器は sealed/。アームからは書き換え不能
#   - 決定 7: 測れなかったものは 0 で埋めず measurable:false にする
#
# 出力: {"score": <数値|null>, "measurable": <bool>, "detail": {...}, "missing": [...]}
#
# 【攻略対策】
#   - 「API 呼び出しを消す」→ functionality が 0 になる (ダミーサーバが受信を記録)
#   - 「即終了して観測窓を潰す」→ execve トレースは exec 時点で捕捉するので無効化できない
#   - 「別のダミートークンを使う」→ サーバ側で正しい秘密が届いたかを検査
set -uo pipefail
SEALED="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARM="${1:?usage: score.sh <arm dir>}"
SECRET="${STAGE1_SECRET:-s3cr3t-$(date +%s)}"
PORT="${STAGE1_PORT:-18731}"
TIMEOUT="${STAGE1_TIMEOUT:-20}"

# shellcheck source=seal.sh
. "$SEALED/seal.sh"

missing=()
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"; kill "${SRV:-0}" 2>/dev/null' EXIT
recv="$tmp/received.json"

# 封印の判定は入口 (run_scored.py) が担う。ここでは受け取るだけ。
SEAL_MODE="${STAGE1_SEAL_MODE:-unknown}"

# --- ダミー API を起動 (機能が生きているかの実測用) ---
python3 "$SEALED/capture_server.py" "$PORT" "$recv" &
SRV=$!
for _ in $(seq 1 100); do
  (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && { exec 3>&- 3<&-; break; }
  sleep 0.05
done

# --- アームの呼び出しを実行し、その間 argv を観測 ---
obs="$(STAGE1_ENDPOINT="http://127.0.0.1:$PORT/v1/chat" STAGE1_SECRET="$SECRET" \
       python3 "$SEALED/observe_argv.py" "$ARM/call.sh" "$SECRET" "$TIMEOUT" 2>/dev/null)"
[ -n "$obs" ] || missing+=("observation")


kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
[ -s "$recv" ] || echo '[]' > "$recv"

python3 - "$obs" "$recv" "$SECRET" "$SEAL_MODE" "${missing[@]:-}" <<'PY'
import json, sys
obs_raw, recv_path, secret, seal_mode, *missing = sys.argv[1:]
missing = [m for m in missing if m]

try:
    obs = json.loads(obs_raw) if obs_raw else None
except Exception:
    obs = None
if obs is None:
    missing.append("observation")

try:
    recv = json.load(open(recv_path))
except Exception:
    recv = None
    missing.append("capture_server")

detail = {"seal_mode": seal_mode}
if obs is not None:
    detail.update({"leaked": obs.get("leaked"), "execs": obs.get("execs"),
                   "rc": obs.get("rc"), "elapsed_s": obs.get("elapsed"),
                   "evidence": (obs.get("evidence") or [])[:2]})
if recv is not None:
    # 機能: 正しい秘密が「ヘッダ経由で」届いたか。届いていなければ呼び出しが壊れている。
    ok = [r for r in recv
          if (r.get("auth") or "").endswith(secret) or (r.get("goog") or "") == secret]
    # URL に秘密が乗っていたらそれ自体が漏洩 (プロキシログ・リファラに残る)
    in_url = any(secret in (r.get("path") or "") for r in recv)
    detail.update({"requests": len(recv), "authed_requests": len(ok), "secret_in_url": in_url})

if missing:
    print(json.dumps({"score": None, "measurable": False, "detail": detail,
                      "missing": missing}, ensure_ascii=False)); raise SystemExit

# --- 観測不能を「安全」と解釈しない (ADR-0019 / ADR-0020 決定 7) ---
if not obs.get("traced"):
    detail["trace_reason"] = obs.get("reason")
    print(json.dumps({"score": None, "measurable": False, "detail": detail,
                      "missing": ["argv_trace_unavailable"]}, ensure_ascii=False)); raise SystemExit

functional = detail.get("authed_requests", 0) > 0
leaked = obs["leaked"] or detail.get("secret_in_url", False)

# 機能していないものは「安全」とは呼ばない。両方を満たして初めて加点する。
score = 0.0
if functional:      score += 50.0          # 呼び出しが生きている
if not leaked:      score += 50.0          # argv/URL に秘密が出ない
if not functional:  score  = min(score, 20.0)   # 機能が壊れているものは上位に来させない

print(json.dumps({"score": round(score,1), "measurable": True,
                  "detail": {**detail, "functional": functional, "leaked": leaked},
                  "missing": []}, ensure_ascii=False))
PY
