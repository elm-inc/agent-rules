#!/usr/bin/env bash
# docs-publish の依存 (markdown-it / mermaid / puppeteer-core) をオンデマンドで用意する。
# node_modules はリポにコミットしない (mermaid が重い) ため、初回だけ導入する (ADR-0005 方式)。
# 冪等: 既に入っていれば即 return。並行呼び出しは flock で直列化する。
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="/tmp/agent-rules-docs-publish-deps.lock"   # /tmp 固定 (TMPDIR 変動で単一化が破れる)

# 既に mermaid が入っていれば何もしない (最も軽い判定)。
if [ -f "$SKILL_DIR/node_modules/mermaid/dist/mermaid.min.js" ]; then
  exit 0
fi

command -v node >/dev/null 2>&1 || { echo "ERROR: node が必要です (18+)。" >&2; exit 1; }
command -v npm  >/dev/null 2>&1 || { echo "ERROR: npm が必要です。" >&2; exit 1; }

echo "docs-publish: 依存を導入します (初回のみ・数十秒)..." >&2
# flock で直列化し、ロック取得後に再チェック (並行起動で二重 install しない)。
flock -w 300 "$LOCK" bash -c '
  set -uo pipefail
  cd "'"$SKILL_DIR"'" || exit 1
  [ -f node_modules/mermaid/dist/mermaid.min.js ] && exit 0
  if [ -f package-lock.json ]; then
    npm ci --no-audit --no-fund
  else
    npm install --no-audit --no-fund
  fi
'
rc=$?
if [ "$rc" -ne 0 ] || [ ! -f "$SKILL_DIR/node_modules/mermaid/dist/mermaid.min.js" ]; then
  echo "ERROR: 依存の導入に失敗しました (rc=$rc)。ネットワークと node/npm を確認してください。" >&2
  exit 1
fi
echo "docs-publish: 依存の導入が完了しました。" >&2
