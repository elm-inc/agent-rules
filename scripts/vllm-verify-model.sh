#!/usr/bin/env bash
# vllm-verify-model.sh — HF Hub からダウンロードしたモデルの safetensors 整合性検証
#
# サプライチェーン対策: 公式組織 (Qwen / deepseek-ai / RedHatAI など) のモデルが
# 改ざんされていないかを HF API の SHA を使ってローカルファイルと比較する。
#
# Usage:
#   bash vllm-verify-model.sh Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
#   bash vllm-verify-model.sh deepseek-ai/DeepSeek-R1-Distill-Qwen-14B

set -uo pipefail

MODEL="${1:-}"
if [ -z "$MODEL" ]; then
  echo "Usage: $0 <org/repo>" >&2
  exit 2
fi

# Allowed publishers (改ざんリスク最小化のための allowlist)
ALLOWED='^(Qwen|deepseek-ai|RedHatAI|mistralai|google|meta-llama)/'
if ! echo "$MODEL" | grep -qE "$ALLOWED"; then
  echo "ERROR: $MODEL is not in the trusted publisher allowlist." >&2
  echo "Allowed orgs: Qwen, deepseek-ai, RedHatAI, mistralai, google, meta-llama" >&2
  exit 3
fi

CACHE="${HF_HUB_CACHE:-$HOME/.cache/huggingface/hub}"
REPO_DIR=$(echo "$MODEL" | sed 's|/|--|g' | sed 's/^/models--/')
SNAP_DIR="$CACHE/$REPO_DIR/snapshots"

if [ ! -d "$SNAP_DIR" ]; then
  echo "ERROR: $MODEL not found in $CACHE — download first with 'hf download $MODEL'" >&2
  exit 4
fi

# HF API から file list + sha を取得
echo "Fetching authoritative SHA from HF Hub..."
API_RESP=$(curl -sf "https://huggingface.co/api/models/$MODEL/tree/main?recursive=true")
if [ -z "$API_RESP" ]; then
  echo "ERROR: failed to fetch model tree from HF" >&2
  exit 5
fi

# safetensors のみ検証 (最重要、メイン model weight)
ok=0
fail=0
echo "$API_RESP" | jq -r '.[] | select(.type == "file" and (.path | test("\\.safetensors$"))) | "\(.path)\t\(.lfs.sha256 // "")"' | \
while IFS=$'\t' read -r path sha; do
  if [ -z "$sha" ]; then
    echo "  skip: $path (no LFS SHA — not LFS-tracked)"
    continue
  fi
  # snapshot/<commit>/<path> として cached
  local_file=$(find "$SNAP_DIR" -name "$(basename "$path")" -type f -o -name "$(basename "$path")" -type l 2>/dev/null | head -1)
  if [ -z "$local_file" ] || [ ! -e "$local_file" ]; then
    echo "  missing: $path"
    fail=$((fail + 1))
    continue
  fi
  # symlink を解決して実体の sha256 を計算
  actual=$(sha256sum "$(readlink -f "$local_file")" | awk '{print $1}')
  if [ "$actual" = "$sha" ]; then
    echo "  ok: $path"
    ok=$((ok + 1))
  else
    echo "  TAMPERED: $path"
    echo "    expected: $sha"
    echo "    actual:   $actual"
    fail=$((fail + 1))
  fi
done

if [ $fail -gt 0 ]; then
  echo ""
  echo "RESULT: $ok OK, $fail FAILED — model integrity compromised" >&2
  exit 1
fi
echo ""
echo "RESULT: all $ok safetensors files verified OK"
