# zellij session hygiene helpers (agent-rules)
# sourced from ~/.bashrc via install.sh. See docs/setup/session-management.md
#
# 目的: 裸 `zellij` 起動による自動命名 (kind-panda 等) の増殖と EXITED 死骸の蓄積を防ぐ。

# per-project の named session に attach、無ければ作成 (引数省略時はカレントディレクトリ名)。
# ZJ_TAG (or ssh 転送された LC_ZJ_TAG) があればセッション名に付与し、同一フォルダでも
# クライアント/マシンごとに別セッションへ分離する (共有ホストに複数クライアントで attach する時のミラー回避)。
# tag 未設定なら従来どおりフォルダ名のみ。正確に名前を指定したいときは `command zellij attach --create <名>` で迂回。
zj() {
    local base="${1:-${PWD##*/}}"
    local tag="${ZJ_TAG:-${LC_ZJ_TAG:-}}"
    local name="${base}${tag:+-$tag}"
    name="${name//[^A-Za-z0-9_-]/-}"
    command zellij attach --create "$name"
}

# 裸 `zellij` (引数なし) も zj 経由にして cwd 名セッションに集約する。
# サブコマンド/オプション付き (list-sessions, kill-session, attach foo, --version 等) は素通し。
# ランダム名で新規が欲しいときは `command zellij` で迂回。
zellij() {
    if [ "$#" -eq 0 ]; then
        zj
    else
        command zellij "$@"
    fi
}

alias zjreap='command zellij delete-all-sessions -y'   # EXITED (死骸) を一掃。実行中は触らない
alias zjls='command zellij list-sessions'
