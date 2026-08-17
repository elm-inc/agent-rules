#!/usr/bin/env bash
# vllm-verify-model.sh — HF Hub からダウンロードしたモデルの safetensors 整合性検証
#
# サプライチェーン対策。2 つの信頼経路のどちらかを満たすことを要求する:
#   (A) 信頼できる公開組織 (allowlist) のモデルである
#   (B) config/models.yml に **commit SHA で pin して** 登録されている (ADR-0017)
#
# (B) を用意したのは、必要な量子化版を公式 org が出さないケースがあるため。
# org 単位の信頼が使えないときは「特定の 1 コミットだけを信頼する」に落とす。
#
# Usage:
#   bash vllm-verify-model.sh Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8   # model-doctor:allow (許可 org の例)
#   bash vllm-verify-model.sh cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit   # 台帳 pin 経由
#
# 終了コード: 0=検証OK, 1=改ざん/欠損, 2=引数誤り, 3=信頼できない発行元, 4=未DL, 5=API失敗

set -uo pipefail

MODEL="${1:-}"
if [ -z "$MODEL" ]; then
  echo "Usage: $0 <org/repo>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEDGER="${SCRIPT_DIR}/../config/models.yml"

# --- 信頼経路 (A): 公開組織 allowlist ---
# nvidia は ADR-0017 で追加 (Blackwell 向け NVFP4 の公式配布元)。
ALLOWED='^(Qwen|deepseek-ai|RedHatAI|nvidia|mistralai|google|meta-llama)/'

# --- 信頼経路 (B): 台帳に SHA pin 付きで登録済みか ---
PINNED_REV=""
if [ -f "$LEDGER" ]; then
  PINNED_REV="$(python3 -c "
import sys, yaml
try:
    d = yaml.safe_load(open('$LEDGER'))
except Exception:
    sys.exit(0)
for m in (d.get('active') or []):
    if m.get('id') == '$MODEL' and m.get('revision'):
        print(m['revision'])
        break
" 2>/dev/null)"
fi

if echo "$MODEL" | grep -qE "$ALLOWED"; then
  echo "trust: allowlisted publisher"
elif [ -n "$PINNED_REV" ]; then
  echo "trust: pinned in config/models.yml @ ${PINNED_REV}"
else
  echo "ERROR: $MODEL は信頼できる発行元ではありません。" >&2
  echo "  経路A: 許可 org (Qwen, deepseek-ai, RedHatAI, nvidia, mistralai, google, meta-llama)" >&2
  echo "  経路B: config/models.yml の active に revision (commit SHA) 付きで登録する" >&2
  exit 3
fi

# pin されているなら、その commit を検証対象にする (main は動きうるため)
REF="${PINNED_REV:-main}"

CACHE="${HF_HUB_CACHE:-$HOME/.cache/huggingface/hub}"
REPO_DIR=$(echo "$MODEL" | sed 's|/|--|g' | sed 's/^/models--/')
SNAP_DIR="$CACHE/$REPO_DIR/snapshots"

if [ ! -d "$SNAP_DIR" ]; then
  echo "ERROR: $MODEL not found in $CACHE — download first with 'hf download $MODEL'" >&2
  exit 4
fi

# pin 時は、その commit の snapshot が実在することも確認する
if [ -n "$PINNED_REV" ] && [ ! -d "$SNAP_DIR/$PINNED_REV" ]; then
  echo "ERROR: pin された commit ${PINNED_REV} の snapshot がローカルにありません。" >&2
  echo "  再取得: hf download $MODEL --revision $PINNED_REV" >&2
  exit 4
fi

echo "Fetching authoritative SHA from HF Hub (ref=${REF})..."
API_RESP=$(curl -sf "https://huggingface.co/api/models/$MODEL/tree/${REF}?recursive=true")
if [ -z "$API_RESP" ]; then
  echo "ERROR: failed to fetch model tree from HF" >&2
  exit 5
fi

# safetensors のみ検証 (メイン model weight)。
# 注意: while をパイプの右辺に置くとサブシェルになり ok/fail が親に伝わらない
# (以前の実装はこれで「改ざんを検出しても exit 0」になっていた)。
# プロセス置換で親シェルのまま回す。
ok=0
fail=0
while IFS=$'\t' read -r path sha; do
  [ -n "$path" ] || continue
  if [ -z "$sha" ]; then
    echo "  skip: $path (no LFS SHA — not LFS-tracked)"
    continue
  fi
  if [ -n "$PINNED_REV" ]; then
    local_file="$SNAP_DIR/$PINNED_REV/$path"
  else
    local_file=$(find "$SNAP_DIR" \( -name "$(basename "$path")" -type f -o -name "$(basename "$path")" -type l \) 2>/dev/null | head -1)
  fi
  if [ -z "$local_file" ] || [ ! -e "$local_file" ]; then
    echo "  missing: $path"
    fail=$((fail + 1))
    continue
  fi
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
done < <(echo "$API_RESP" | jq -r '
  .[]
  | select(.type == "file" and (.path | test("\\.safetensors$")))
  # HF tree API は SHA256 を .lfs.oid で返す (.lfs.sha256 は存在しない)。
  # 以前の実装は .lfs.sha256 を見ていたため全ファイルを skip していた。
  | "\(.path)\t\(.lfs.oid // "")"')

if [ "$ok" -eq 0 ] && [ "$fail" -eq 0 ]; then
  echo "" >&2
  echo "RESULT: 検証対象の safetensors が 1 つも見つかりませんでした (想定外)" >&2
  exit 1
fi

if [ "$fail" -gt 0 ]; then
  echo ""
  echo "RESULT: $ok OK, $fail FAILED — model integrity compromised" >&2
  exit 1
fi
echo ""
echo "RESULT: all $ok safetensors files verified OK (ref=${REF})"
