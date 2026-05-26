---
name: cli-help
description: モダン CLI ツール (rg/fd/bat/eza/dust/btm/procs/delta/sd/hyperfine/tldr/jless/tokei/zoxide) の使い方を即引きする。「rg の使い方」「grep の代替」「du より見やすいやつ」などの問い合わせで cheatsheet から該当箇所を抜粋する
argument-hint: "<tool-name | old-command>"
allowed-tools: Read, Bash(awk *)
---

# /cli-help — モダン CLI ツールの即引き

`$ARGUMENTS` を以下のように解釈する:

- **空**: 「旧→新 早見表」セクションを抜粋表示
- **新ツール名** (`rg`, `fd`, `bat`, `eza`, `dust`, `btm`, `procs`, `delta`, `sd`, `hyperfine`, `tldr`, `jless`, `tokei`, `zoxide`): 該当 H2 セクションを抜粋
- **旧コマンド名**: 以下のマッピングで対応する新ツールに変換してから抜粋
  - `grep`→`rg` / `find`→`fd` / `cat`→`bat` / `top`/`htop`→`btm` / `du`→`dust`
  - `sed`→`sd` / `ps`/`pstree`→`procs` / `ls`/`tree`→`eza` / `cd`→`zoxide`
  - `time`→`hyperfine` / `man`→`tldr` / `jq`→`jless` / `wc`→`tokei`

## 手順

1. `~/.claude/skills/cli-help/cheatsheet.md` を Read する
2. 引数から検索対象セクション名を決定する (上記マッピング表参照)
3. 該当 H2 ブロック (`## <tool>` から次の `## ` の直前まで) を**そのまま引用**して回答
4. 末尾に 1 行案内: 「より深く調べたければ `tldr <tool>` または `cheat <tool>` (シェル関数) を試してください」

## 重要

- **創作禁止**: cheatsheet に書かれていない flag や用法を勝手に補わない (古い・誤った情報を出さないため)
- 引数のツールが cheatsheet にない場合: ない旨を明確に伝え、近い候補があれば提示する
- インストール状況が不明なら「`command -v <bin>` で確認してください」と一文添える

## 使用例

- `/cli-help rg` → rg セクションを抜粋
- `/cli-help grep` → 旧コマンドマッピングで rg セクションを抜粋
- `/cli-help` → 早見表セクションを表示
- `/cli-help foo` → cheatsheet にない旨を返答
