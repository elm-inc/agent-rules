# shellcheck shell=bash
# Modern CLI cheatsheet & soft reminder.
# Sourced from ~/.bashrc. Safe to source multiple times.
#
# Disable hints only: export MODERN_CLI_HINTS=0
# Disable everything : remove the source line from ~/.bashrc.

# Interactive shells only
case $- in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac

# ---- cheat: cheatsheet 即引き ------------------------------------------------
cheat() {
  local cs="${MODERN_CLI_CHEATSHEET:-$HOME/.claude/skills/cli-help/cheatsheet.md}"
  if [ ! -f "$cs" ]; then
    printf 'cheatsheet not found: %s\n' "$cs" >&2
    return 1
  fi

  local viewer
  if command -v bat >/dev/null 2>&1; then
    viewer="bat --style=plain --paging=always -l md"
  elif command -v batcat >/dev/null 2>&1; then
    viewer="batcat --style=plain --paging=always -l md"
  else
    viewer="${PAGER:-less} -R"
  fi

  if [ $# -eq 0 ]; then
    eval "$viewer \"\$cs\""
    return
  fi

  local query="$1"
  if [ "$query" = "-i" ] || [ "$query" = "--interactive" ]; then
    if ! command -v fzf >/dev/null 2>&1; then
      printf 'fzf not installed.\n' >&2
      return 1
    fi
    local pick
    pick=$(grep -E '^## ' "$cs" | sed 's/^## //' | fzf --prompt='tool> ') || return
    query="${pick%% *}"
  fi

  # old command -> new tool mapping
  case "$query" in
    grep) query=rg ;;
    find) query=fd ;;
    cat)  query=bat ;;
    top|htop) query=btm ;;
    du)   query=dust ;;
    sed)  query=sd ;;
    ps|pstree) query=procs ;;
    ls|tree) query=eza ;;
    cd)   query=zoxide ;;
    time) query=hyperfine ;;
    man)  query=tldr ;;
    jq)   query=jless ;;
    wc)   query=tokei ;;
  esac

  awk -v t="$query" '
    /^## / { f = ($0 ~ "^## " t " ") }
    f
  ' "$cs" | eval "$viewer"
}

# ---- soft reminder: 古いコマンドを叩いたら 1 度だけ hint --------------------
# Use `function NAME { ... }` syntax (not `NAME() { ... }`) so the function-name
# token is not subject to alias expansion at parse time. Combined with a
# pre-pass unalias (run as a separate top-level statement so it executes BEFORE
# the function-defining if-block is parsed), this avoids both:
#   - the syntax error when alias grep='grep --color=auto' would expand to
#     `grep --color=auto() { ... }` at parse time, and
#   - the cosmetic double `--color=auto` flag at call time when alias stays.
if [ "${MODERN_CLI_HINTS:-1}" != "0" ]; then
  unalias grep find cat top du sed ps 2>/dev/null || :
fi

if [ "${MODERN_CLI_HINTS:-1}" != "0" ]; then

  _mcli_hint() {
    local key="$1" msg="$2"
    local flag="_MCLI_HINTED_${key}"
    [ -n "${!flag:-}" ] && return
    printf '\033[2;33m[hint] %s  (bypass: command %s ...)\033[0m\n' "$msg" "$key" >&2
    printf -v "$flag" '%s' 1
    export "$flag"
  }

  function grep { _mcli_hint grep "rg のほうが速い: cheat rg";        command grep --color=auto "$@"; }
  function find { _mcli_hint find "fd のほうが直感的: cheat fd";       command find "$@"; }
  function cat  { _mcli_hint cat  "bat で syntax highlight: cheat bat"; command cat "$@"; }
  function top  { _mcli_hint top  "btm が見やすい: cheat btm";         command top "$@"; }
  function du   { _mcli_hint du   "dust が直感的: cheat dust";         command du "$@"; }
  function sed  { _mcli_hint sed  "単純置換は sd が安全: cheat sd";    command sed "$@"; }
  function ps   { _mcli_hint ps   "procs が読みやすい: cheat procs";   command ps "$@"; }

fi
