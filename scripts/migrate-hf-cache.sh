#!/usr/bin/env bash
# migrate-hf-cache.sh — AGENT-16
#
# Phase 7 で判明: ~/models/hub/ は docker volume 経由で root 所有のため、elmo が
# hf download で新規モデルを追加できない (Phase 1 ベンチでは ~/.cache/huggingface/hub/
# に DL して回避)。本スクリプトで cache を ~/.cache/huggingface/hub/ に統一する。
#
# 流れ:
#   1. 確認 (ダウンタイムが発生する)
#   2. vllm-qwen-coder 停止
#   3. ~/models/hub/ → ~/.cache/huggingface/hub/ へ rsync (elmo として)
#   4. 新 cache の root 所有ファイルを elmo に chown (sudo 必要)
#   5. 旧 ~/models/ を ~/models.legacy.YYYYMMDD/ にリネーム (sudo 必要)
#   6. vLLM コンテナを新 volume で再作成
#   7. healthcheck
#
# 想定ダウンタイム: 30-60 分 (rsync 速度次第)
# 必要権限: docker (elmo は所属済) + sudo (chown と mv)

set -uo pipefail

OLD_CACHE="$HOME/models/hub"
NEW_CACHE="$HOME/.cache/huggingface/hub"
LEGACY_DIR="$HOME/models.legacy.$(date +%Y%m%d-%H%M%S)"
MAIN_CONTAINER="${VLLM_MAIN_CONTAINER:-vllm-qwen-coder}"
HF_TOKEN="$(cat ~/.hf_token 2>/dev/null || true)"

echo "===================================================================="
echo "HF cache migration: $OLD_CACHE → $NEW_CACHE"
echo "===================================================================="
echo ""
echo "現状:"
[ -d "$OLD_CACHE" ] && echo "  旧 (root 所有): $(du -sh "$OLD_CACHE" 2>/dev/null)" || { echo "  ERROR: 旧 cache ($OLD_CACHE) が存在しません"; exit 1; }
[ -d "$NEW_CACHE" ] && echo "  新 (elmo 所有): $(du -sh "$NEW_CACHE" 2>/dev/null)" || mkdir -p "$NEW_CACHE"
echo "  ディスク空き: $(df -h "$HOME" | tail -1 | awk '{print $4}')"
echo ""
echo "実行内容:"
echo "  1. docker stop $MAIN_CONTAINER (ダウンタイム開始)"
echo "  2. rsync $OLD_CACHE/ → $NEW_CACHE/"
echo "  3. sudo chown -R elmo:elmo $NEW_CACHE"
echo "  4. sudo mv $HOME/models $LEGACY_DIR (旧 cache の保全)"
echo "  5. docker run で $MAIN_CONTAINER を新 volume で再作成"
echo "  6. healthcheck (~/.cache/huggingface 経由でモデルを再ロード)"
echo ""
echo "想定ダウンタイム: 30-60 分"
echo "sudo パスワード入力が必要なステップ: 3, 4"
echo ""
read -r -p "続行しますか? (yes/no) " confirm
[ "$confirm" = "yes" ] || { echo "abort"; exit 1; }

now() { date '+%Y-%m-%d %H:%M:%S'; }

echo ""
echo "[$(now)] === step 1: stopping main vLLM ==="
docker stop "$MAIN_CONTAINER" > /dev/null
docker rm "$MAIN_CONTAINER" > /dev/null

echo ""
echo "[$(now)] === step 2: rsync (skip files already in new cache) ==="
# --ignore-existing で新 cache に既にあるファイルは触らない (Phase 1 で DL 済み分を保護)
# -a でパーミッション・タイムスタンプ保持
# --info=progress2 で全体進捗表示
rsync -a --ignore-existing --info=progress2 "$OLD_CACHE/" "$NEW_CACHE/"
rc=$?
[ $rc -ne 0 ] && { echo "rsync failed ($rc)"; exit $rc; }

echo ""
echo "[$(now)] === step 3: chown new cache to elmo (sudo required) ==="
sudo chown -R elmo:elmo "$NEW_CACHE"

echo ""
echo "[$(now)] === step 4: rename old cache to legacy (sudo required) ==="
sudo mv "$HOME/models" "$LEGACY_DIR"
echo "  旧 cache を $LEGACY_DIR に保全 (確認後に削除可)"

echo ""
echo "[$(now)] === step 5: recreate vLLM container with new volume ==="
docker run -d \
  --name "$MAIN_CONTAINER" \
  --restart unless-stopped \
  --gpus all --ipc=host \
  -p 8000:8000 \
  -v "$HOME/.cache/huggingface":/root/.cache/huggingface \
  -e HUGGING_FACE_HUB_TOKEN="$HF_TOKEN" \
  -e HF_HUB_ENABLE_HF_TRANSFER=1 \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  vllm/vllm-openai:latest \
  --model cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit \
  --revision 4bd30395b72ea6045edd04806c4fea448d4467b3 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.88 \
  --enforce-eager \
  --served-model-name qwen-coder > /dev/null

echo ""
echo "[$(now)] === step 6: healthcheck (waiting for vLLM ready, up to 5 min) ==="
for i in $(seq 1 60); do
  if curl -sf -m 3 http://localhost:8000/v1/models > /dev/null 2>&1; then
    echo "  vLLM healthy at $(now)"
    break
  fi
  sleep 5
done

# 最終確認
if ! curl -sf -m 3 http://localhost:8000/v1/models > /dev/null; then
  echo ""
  echo "!! vLLM not healthy after 5 min. Check logs:"
  echo "   docker logs $MAIN_CONTAINER"
  exit 2
fi

echo ""
echo "===================================================================="
echo "Migration complete @ $(now)"
echo "===================================================================="
echo ""
echo "後続作業:"
echo "  - hf download <model> で新規モデルを ~/.cache/huggingface/hub/ に追加可能"
echo "  - 旧 cache 確認後に削除: sudo rm -rf $LEGACY_DIR"
echo "  - AGENT-14 systemd unit を install 済みなら、unit の -v も既に新パスに揃っている"
echo ""
echo "新 cache サイズ: $(du -sh "$NEW_CACHE" 2>/dev/null)"
echo "ディスク空き:   $(df -h "$HOME" | tail -1 | awk '{print $4}')"
