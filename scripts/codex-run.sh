#!/usr/bin/env bash
# codex-run.sh — Codex CLI を起動する前に、外部送信の区分を確認する薄いラッパ (根拠: ADR-0023)。
#
# なぜラッパが要るか:
#   Codex は作業中のリポジトリの内容を OpenAI に送る。スキルが `codex` を直接呼ぶと、
#   .harness.yml の区分 (sensitivity) に照らした通知が出ない。ここを通すことで
#   /codex-review・/codex-task・/codex-audit のどの経路でも【送信の前に】伝える。
#   遮断はしない (通知のみ)。GPT-6 Astra は scripts/codex-astra.sh (同じ確認を内蔵) を使う。
#
# 使い方 (codex にそのまま渡る):
#   ~/repos/github.com/elm-inc/agent-rules/scripts/codex-run.sh review --uncommitted
#   ~/repos/github.com/elm-inc/agent-rules/scripts/codex-run.sh exec --sandbox read-only "..."

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

command -v codex >/dev/null 2>&1 || { echo "codex CLI が見つかりません" >&2; exit 127; }
[ "$#" -gt 0 ] || { echo "usage: $0 <codex サブコマンドと引数>" >&2; exit 2; }

# 送信前の確認 (止めない)。検知器を起動できないときも黙らない。
# --version / --help / login 等はリポジトリの内容を送らないので確認しない (ノイズを出さない)。
case "$1" in
  --version|-V|--help|-h|help|login|logout|completion) exec codex "$@" ;;
esac
if command -v python3 >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/harness.py" ]; then
  python3 "$SCRIPT_DIR/harness.py" egress-check --vendor openai --codex -- "$@" </dev/null >&2 || true
else
  echo "⚠ 外部送信の確認 (ADR-0023): 検知器 (harness.py) を起動できず、区分を判定できませんでした" >&2
fi

exec codex "$@"
