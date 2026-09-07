#!/usr/bin/env bash
# curl-secret.sh — API キーを argv に載せずに curl を呼ぶ共有ヘルパ。
#
# 背景 (Issue #40):
#   /proc/<pid>/cmdline は既定で world-readable なので、
#   `curl -H "Authorization: Bearer $KEY"` は**呼び出しが走っている間**  # secret-argv:allow (アンチパターンの説明)
#   同一ホストの任意のローカルユーザに鍵を晒す。
#   `?key=` の URL 埋め込みは argv に加えてプロキシログ・リファラにも乗るためさらに悪い。
#
# 仕組み:
#   curl の --config はヘッダをファイルから読める。プロセス置換 <(...) を使うと
#   中身はパイプ経由で渡り、argv には /dev/fd/N しか現れない。
#   printf は **bash builtin** なので printf 自身も argv に鍵を載せない。
#
# 使い方:
#   . "$(dirname "$0")/lib/curl-secret.sh"
#   curl_auth_bearer "$TOKEN" -sS -d "$PAYLOAD" "$URL"
#   curl_auth_header "x-goog-api-key" "$TOKEN" -sS -d "$PAYLOAD" "$URL"
#
# 注意:
#   - 秘密に " や改行が含まれると config の解釈が壊れる。API キーは通常
#     英数字・ハイフン・アンダースコアのみなので実害は無いが、検査して弾く。
#   - stdin を使う呼び出し (-d @-) とは併用できる (--config はプロセス置換で
#     別の fd を使うため stdin を奪わない)。

# 秘密として妥当か検査する。壊れた config を作らせない。
_curl_secret_validate() {
  case "$1" in
    *'"'*|*$'\n'*|*$'\r'*|'')
      echo "curl-secret: 秘密に使えない文字が含まれるか空です" >&2; return 1 ;;
  esac
  return 0
}

# curl_auth_header <ヘッダ名> <秘密> [curl の引数...]
curl_auth_header() {
  local name="$1" secret="$2"; shift 2
  _curl_secret_validate "$secret" || return 1
  curl --config <(printf 'header = "%s: %s"\n' "$name" "$secret") "$@"
}

# curl_auth_bearer <秘密> [curl の引数...]
curl_auth_bearer() {
  local secret="$1"; shift
  curl_auth_header "Authorization" "Bearer $secret" "$@"
}
