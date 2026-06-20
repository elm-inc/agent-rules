# zellij session hygiene helpers (agent-rules)
# sourced from ~/.bashrc via install.sh. See docs/setup/session-management.md
#
# 目的: 裸 `zellij` 起動による自動命名 (kind-panda 等) の増殖と EXITED 死骸の蓄積を防ぐ。

# per-project の named session に attach、無ければ作成 (引数省略時はカレントディレクトリ名)
zj() {
    local name="${1:-${PWD##*/}}"
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
