#!/usr/bin/env bash
# ensure-vllm.sh — vLLM をオンデマンド起動する (常駐をやめ、ローカル LLM スキル呼び出し時だけ立ち上げる)
#
# 目的: GPU を普段は解放しておき、/local-review /test-generate /test-data などが
#       必要とした時だけ vLLM を起動する。起動後はアイドル監視 (vllm-idle-watch.sh) を
#       1 つ常駐させ、一定時間使われなければ自動停止して GPU を解放する。
#
# sudo 不要 (elmo は docker グループ所属)。常駐 systemd 方式からの移行は
# `sudo systemctl disable --now vllm-qwen-coder` を一度だけ実行する。
#
# 常駐 (opt-in) との共存: systemd の vllm-qwen-coder が active なら、本スクリプトは
# 起動・停止・watcher に一切干渉せず healthy 確認のみ行う (相互 churn を防ぐ)。
#
# Usage:
#   bash ensure-vllm.sh            # 稼働保証 (未稼働なら起動して healthy まで待機)
#   bash ensure-vllm.sh stop       # 即時停止 (GPU 解放)
#   bash ensure-vllm.sh status     # running / 別モデル稼働 / stopped と watcher の有無を表示
#
# 終了コード (up): 0=稼働中, 1=起動失敗(GPU競合等), 2 は内部用 (呼び出し側には 1 を返す)
#
# 主な環境変数 (デフォルトは常駐運用と同一設定):
#   VLLM_PORT=8000  VLLM_MODEL=cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit
#   VLLM_REVISION=4bd30395b72ea6045edd04806c4fea448d4467b3  (台帳 pin: ADR-0017)
#   VLLM_SERVED_NAME=qwen-coder  VLLM_MAX_LEN=32768  VLLM_GPU_MEM_UTIL=0.85
#   VLLM_CPU_OFFLOAD_GB=0  VLLM_HF_CACHE=$HOME/.cache/huggingface
#   VLLM_START_TIMEOUT=300 (秒)  VLLM_IDLE_MINUTES=15  VLLM_IDLE_POLL=60 (watcher へ継承)
#   VLLM_IMAGE=vllm/vllm-openai:latest  ← 安定運用では版を pin 推奨 (例 :v0.21.0)。
#     :latest のままでもメトリクス改名で watcher が誤停止しないよう idle-watch 側は fail-safe。
set -uo pipefail

PORT="${VLLM_PORT:-8000}"
BASE_URL="http://localhost:${PORT}/v1"
CONTAINER="vllm-qwen-coder"
IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:latest}"
MODEL="${VLLM_MODEL:-cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit}"
# 公式 org ではないため commit で pin する (config/models.yml と一致させること)
REVISION="${VLLM_REVISION:-4bd30395b72ea6045edd04806c4fea448d4467b3}"
SERVED_NAME="${VLLM_SERVED_NAME:-qwen-coder}"
MAX_LEN="${VLLM_MAX_LEN:-32768}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.85}"
# AWQ 4bit (重み 16.9 GiB) なので offload 不要。0 のままにすること —
# offload を入れると PCIe 往復が律速になり 6 tok/s 時代に逆戻りする (ADR-0017)
CPU_OFFLOAD_GB="${VLLM_CPU_OFFLOAD_GB:-0}"
HF_CACHE="${VLLM_HF_CACHE:-$HOME/.cache/huggingface}"
START_TIMEOUT="${VLLM_START_TIMEOUT:-300}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCH="${SCRIPT_DIR}/vllm-idle-watch.sh"
WATCH_LOCK="/tmp/vllm-idle-watch.lock"   # /tmp 固定 (TMPDIR 変動で単一化が破れるのを防ぐ)
WATCH_LOG="/tmp/vllm-idle-watch.log"
START_LOCK="/tmp/vllm-ensure-start.lock"
LEASE="/tmp/vllm-last-ensure"            # up 呼び出し=直近の利用意図。watcher が idle タイマーに反映 (TOCTOU 緩和)

log() { echo "[ensure-vllm] $*" >&2; }
# /v1/models が応答し、かつ served-model-name が一致することを確認 (:8000 の別サーバを主力と誤認しない)
healthy() { curl -sf -m 5 "${BASE_URL}/models" 2>/dev/null | grep -q "\"${SERVED_NAME}\""; }

# systemd 常駐 (opt-in) 管理下か。read-only、sudo 不要。
systemd_managed() {
  command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet vllm-qwen-coder 2>/dev/null
}

# アイドル監視を 1 つだけ常駐させる (flock -n で多重起動防止、setsid で完全デタッチ)。
# 9>&- で親の起動ロック (START_LOCK) を子に継承させない。watcher 不在は警告する。
#
# 呼び出し元の cgroup から逃がす (AGENT-28):
#   systemd の oneshot サービス (ai-trading-platform の atp-daily.service 等) から呼ばれると、
#   watcher はそのサービスの cgroup に入る。サービスが終わると KillMode=control-group で
#   cgroup ごと SIGTERM され、**setsid では逃げられない** (セッションは変わっても cgroup は同じ)。
#   コンテナ (docker の cgroup) だけが残り、watcher 不在のまま 2026-10-15 17:58 から
#   16 時間 GPU 27.5GB を握り続けた。日次運用のたびに再発する。
#
#   対策: user systemd の transient service (`vllm-idle-watch`) として起動する。プロセスを
#   生むのは user manager なので、呼び出し元の cgroup にも fd にも一切つながらない。
#   `systemd-run --scope` を & で投げる案は**実測で失敗した** — scope へ移る前に本スクリプトが
#   exit し、その瞬間にサービスの cgroup ごと消される (起動の登録が終わるまで戻らない
#   service 方式なら、この競合が原理的に無い)。
#   user systemd が無い環境 (CI・コンテナ内・cron 等) では従来どおり setsid で起動する。
# watcher 本体 (`bash <path>/vllm-idle-watch.sh`) が動いているか。
# **行頭から完全一致で見る** — `pgrep -f vllm-idle-watch.sh` だと、ファイル名を含む
# あらゆるコマンド (エディタ・cat・Claude の Bash) に当たり、「居る」と誤認して起動を
# 飛ばす (実測で起きた)。誤認の向きが「watcher 不在で GPU を握り続ける」なので緩めない。
watcher_alive() { pgrep -f '^bash [^ ]*vllm-idle-watch\.sh$' >/dev/null 2>&1; }

start_watcher() {
  if [ ! -x "$WATCH" ]; then
    log "WARN: watcher 不在 ($WATCH)。アイドル自動停止が効きません"
    return 0
  fi
  # 既に居れば起動しない (多重起動の本当の防止は flock。ここは毎回の無駄な起動を省くだけ)
  watcher_alive && return 0
  if command -v systemd-run >/dev/null 2>&1; then
    # transient service は呼び出し元の環境を引き継がないので、watcher が読む変数を渡す
    local -a envs=(-E "PATH=$PATH")
    local v
    for v in VLLM_PORT VLLM_IDLE_MINUTES VLLM_IDLE_POLL; do
      [ -n "${!v:-}" ] && envs+=(-E "$v=${!v}")
    done
    # shellcheck disable=SC2016  # $0-$2 は bash -c の中で展開する
    if systemd-run --user --quiet --collect --unit=vllm-idle-watch "${envs[@]}" \
         bash -c 'exec flock -n "$0" bash "$1" >>"$2" 2>&1' "$WATCH_LOCK" "$WATCH" "$WATCH_LOG" \
         </dev/null >/dev/null 2>&1; then
      return 0
    fi
    # user systemd に繋がらない等 → setsid に落とす (flock が多重起動を防ぐ)
  fi
  if command -v setsid >/dev/null 2>&1; then
    setsid flock -n "$WATCH_LOCK" bash "$WATCH" </dev/null >>"$WATCH_LOG" 2>&1 9>&- &
  else
    nohup flock -n "$WATCH_LOCK" bash "$WATCH" </dev/null >>"$WATCH_LOG" 2>&1 9>&- &
  fi
  disown 2>/dev/null || true
}

# :8000 で応答しているモデルの served name (止まっていれば空)。
# healthy() は主力の名前しか見ないので、別モデル (ai-trading-platform の gemma 等) が
# 動いていると status が "stopped" と答えていた — GPU を握っているのに気づけない。
served_now() {
  curl -sf -m 5 "${BASE_URL}/models" 2>/dev/null | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4
}

case "${1:-up}" in
  stop)
    if systemd_managed; then
      log "systemd 常駐管理下です。停止は: sudo systemctl stop vllm-qwen-coder"
      exit 0
    fi
    log "vLLM を停止します..."
    if docker stop "$CONTAINER" >/dev/null 2>&1; then log "停止しました (GPU 解放)"; else log "稼働していません"; fi
    exit 0
    ;;
  status)
    if systemd_managed; then echo "running (systemd 常駐, ${BASE_URL})"; exit 0; fi
    other="$(served_now)"
    if [ -z "$other" ]; then echo "stopped"; exit 0; fi
    if [ "$other" = "$SERVED_NAME" ]; then
      echo "running (${BASE_URL})"
    else
      echo "running: 別モデル ${other} (主力 ${SERVED_NAME} ではない, ${BASE_URL})"
    fi
    # watcher が居なければアイドル自動停止が効かず、GPU を握り続ける (AGENT-28)
    if watcher_alive; then
      echo "watcher: 稼働中 (アイドルで自動停止。経過は ${WATCH_LOG})"
    else
      echo "watcher: 不在 — 自動停止しません。使っていなければ 'ensure-vllm.sh stop' で GPU を解放してください"
    fi
    exit 0
    ;;
esac

# --- up (デフォルト): 稼働保証 ---

# up が呼ばれた = スキルが直後に推論する意図。watcher の idle 停止判定に効かせ、
# healthy→exit 直後に watcher が docker stop する TOCTOU 窓を塞ぐ (M-3)。
touch "$LEASE" 2>/dev/null || true

# systemd 常駐管理下: 起動・停止・watcher に干渉せず healthy 確認のみ
if systemd_managed; then
  healthy && exit 0
  log "systemd 常駐がロード中… healthy を待機 (最大 ${START_TIMEOUT}s)"
  sd_deadline=$(( $(date +%s) + START_TIMEOUT ))
  while ! healthy; do
    if [ "$(date +%s)" -ge "$sd_deadline" ]; then
      log "ERROR: systemd 常駐 vLLM が healthy になりません。'systemctl status vllm-qwen-coder' を確認"
      exit 1
    fi
    sleep 5
  done
  exit 0
fi

# 既に稼働中なら watcher の生存だけ保証して終了
if healthy; then
  start_watcher
  exit 0
fi

# cold-start を flock で直列化 (worktree 並列で同時起動しても殺し合わない)。
# ロック取得後に再 healthy チェックし、待機中に別プロセスが起動済みなら相乗りする。
(
  if ! flock -w "$START_TIMEOUT" 9; then
    log "ERROR: 起動ロックを ${START_TIMEOUT}s 以内に取得できませんでした"
    exit 1
  fi
  healthy && exit 0

  log "vLLM 未稼働 → 起動します (初回モデルロードに 1-2 分)"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true   # 異常終了で残ったコンテナを掃除

  if ! docker run -d \
      --name "$CONTAINER" \
      --gpus all --ipc=host \
      -p "${PORT}:8000" \
      -v "${HF_CACHE}:/root/.cache/huggingface" \
      ${HUGGING_FACE_HUB_TOKEN:+-e HUGGING_FACE_HUB_TOKEN="$HUGGING_FACE_HUB_TOKEN"} \
      -e HF_HUB_ENABLE_HF_TRANSFER=1 \
      -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
      "$IMAGE" \
      --model "$MODEL" \
      ${REVISION:+--revision "$REVISION"} \
      --max-model-len "$MAX_LEN" \
      --gpu-memory-utilization "$GPU_MEM_UTIL" \
      $([ "${CPU_OFFLOAD_GB:-0}" != "0" ] && echo --cpu-offload-gb "$CPU_OFFLOAD_GB") \
      --served-model-name "$SERVED_NAME" >/dev/null; then
    log "ERROR: docker run に失敗しました (GPU が他プロセスで使用中の可能性)。nvidia-smi で確認してください"
    exit 1
  fi

  deadline=$(( $(date +%s) + START_TIMEOUT ))
  while ! healthy; do
    if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
      log "ERROR: コンテナが異常終了しました。直近ログ:"
      docker logs --tail 30 "$CONTAINER" >&2 2>/dev/null || true   # --rm を外したのでログが残る
      exit 1
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      log "${START_TIMEOUT}s 以内に healthy になりませんでした (初回 18GB DL や低速ロードの可能性)"
      exit 2   # まだロード中かもしれない → 呼び出し側で watcher を立てる
    fi
    sleep 5
  done
  exit 0
) 9>"$START_LOCK"
rc=$?

case "$rc" in
  0)
    log "起動完了 (${BASE_URL})。アイドル時は自動停止します (VLLM_IDLE_MINUTES=${VLLM_IDLE_MINUTES:-15})"
    start_watcher
    exit 0
    ;;
  2)
    # まだロード中: watcher を立てて GPU を放置しない (未使用ならアイドル後に自動停止)
    start_watcher
    log "バックグラウンドでロード継続中。'ensure-vllm.sh status' で確認 / 'stop' で中止できます。初回 DL は docs/setup/local-llm.md の手動起動推奨"
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
