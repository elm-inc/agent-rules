#!/usr/bin/env bash
# lint-secret-argv.sh — API キーを curl の argv に載せる書き方を禁止する (Issue #40)
#
# なぜ機械検査が要るか:
#   Issue #40 は「以前から全経路に存在した」。人間の注意では再発を止められないので、
#   model-doctor と同じく **CI で落とす**形にする。
#
# 検出するアンチパターン:
#   -H "Authorization: Bearer $VAR"     鍵が argv に出る
#   -H "x-api-key: $VAR"                同上
#   ?key=$VAR / ?key=${VAR}             argv に加えプロキシログ・リファラにも乗る
#
# 正しい書き方: scripts/lib/curl-secret.sh の curl_auth_bearer / curl_auth_header
#
# 除外: 行内に secret-argv:allow があれば対象外 (model-doctor と同じ逃がし弁)

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

targets=(skills scripts templates agents plugins prompts .github CLAUDE.md RULES.md AGENTS.md)
scan=(); for t in "${targets[@]}"; do [ -e "$t" ] && scan+=("$t"); done

# 秘密らしき変数を argv に埋める形だけを狙う (説明文や固定値は拾わない)
# 注: パターンが '-H' で始まるので grep には必ず -e で渡す (オプションと誤解される)
pattern='-H[[:space:]]+"(Authorization:[[:space:]]*Bearer|x-api-key:|x-goog-api-key:)[[:space:]]*\$\{?[A-Za-z_]|[?&]key=\$\{?[A-Za-z_]'

# gitignore された成果物を走査しない (model-doctor と同じ理由・PR #48)
mapfile -t -d '' files < <(git ls-files -z --cached --others --exclude-standard -- "${scan[@]}" 2>/dev/null)

hits=""
if [ "${#files[@]}" -gt 0 ]; then
  hits="$(printf '%s\0' "${files[@]}" \
    | xargs -0 grep -nHE -e "$pattern" 2>/dev/null \
    | grep -v 'secret-argv:allow' \
    | grep -v '^scripts/lint-secret-argv.sh:')"
fi

if [ -n "$hits" ]; then
  echo "FAIL: API キーを curl の argv に載せる書き方が見つかりました (Issue #40)"
  echo "$hits" | sed 's/^/  /'
  echo ""
  echo "  → scripts/lib/curl-secret.sh の curl_auth_bearer / curl_auth_header を使ってください"
  echo "  → 意図的な例外は行末に  # secret-argv:allow  を付けてください"
  exit 1
fi
echo "ok:   API キーの argv 露出なし (Issue #40 の再発防止)"
