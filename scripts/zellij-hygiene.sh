# zellij session hygiene helpers (agent-rules)
# sourced from ~/.bashrc via install.sh. See docs/setup/session-management.md
#
# 目的: 裸 `zellij` 起動による自動命名 (kind-panda 等) の増殖と EXITED 死骸の蓄積を防ぐ。

# per-project の named session に attach、無ければ作成 (引数省略時はカレントディレクトリ名)
zj() {
    local name="${1:-${PWD##*/}}"
    name="${name//[^A-Za-z0-9_-]/-}"
    zellij attach --create "$name"
}

alias zjreap='zellij delete-all-sessions -y'   # EXITED (死骸) を一掃。実行中は触らない
alias zjls='zellij list-sessions'
