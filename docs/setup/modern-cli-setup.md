# モダン CLI ツール環境 (Rust 製 CLI + soft reminder)

Rust 製モダン CLI (`rg`, `fd`, `bat`, `eza`, `dust`, `btm`, `procs`, `delta`, `sd`, `hyperfine`, `tldr`, `jless`, `tokei`, `zoxide`) を使いこなすための仕組み。使い方の即引きは `/cli-help <tool>` (`grep` などの旧コマンド名からの逆引きにも対応)。

## 仕組み

- **cheat 関数**: シェルで `cheat <tool>` と打つと該当ツールの cheatsheet を表示する
- **soft reminder**: `grep` / `find` / `cat` などの旧コマンドを関数でラップし、実行時にモダン代替を提案する。ラップを回避したいときは `command grep ...` のように `command` を前置する
- **有効化**: `install.sh` が `~/.bashrc` に追記する (idempotent。既に追記済みならスキップ)
- **全停止**: `export MODERN_CLI_HINTS=0`

## ツールの一括導入

`install.sh` 本体はツールの導入を行わない (~/.bashrc への追記のみ)。推奨ツールの一括導入は別スクリプトで行う:

```bash
bash scripts/install-modern-cli.sh   # cargo 経由。導入済みツールはスキップ
```
