---
name: docs-init
description: 新規 or 既存プロジェクトに docs/{adr,architecture,design} の標準構造を展開する。agent-rules/templates/docs/ から雛形をコピーし、不足分のみ追加する (既存ファイルは上書きしない)
argument-hint: "[--force]"
disable-model-invocation: false
allowed-tools: Bash(ls *) Bash(find *) Bash(mkdir *) Bash(cp *) Bash(test *) Read Write Edit
---

# プロジェクト docs 基盤を初期化

カレントワーキングディレクトリ (= git リポジトリのルート) に `docs/` 標準構造を展開する。テンプレートは `~/repos/github.com/elm-inc/agent-rules/templates/docs/` から取得する。

## 引数の解釈

- `--force`: 既存ファイルがあっても上書きする (デフォルトはスキップ)

## 実行手順

### 1. リポジトリのルート確認
```bash
git rev-parse --show-toplevel
```
で取得したパスを以降のベースとする。git リポジトリでなければエラー終了。

### 2. テンプレ展開
コピー元: `/home/elmo/repos/github.com/elm-inc/agent-rules/templates/docs/`
コピー先: `<repo-root>/docs/`

ディレクトリ単位でコピー。**メタ (`_` 接頭辞) と中身で扱いを分ける**:

- **メタ** (`_templates/` 配下のひな形): 単一ソースに追従させるため**常に上書き同期**する (ユーザーが書き換える対象ではない)
- **中身・ガイド** (`README.md`・`cheatsheet.md` 等の連番/通常名): 既存があれば**スキップしてログ出力**。`--force` 指定時のみ上書き

展開対象:

```
docs/README.md
docs/_templates/README.md      # メタ: 常に上書き
docs/_templates/adr.md         # メタ: 常に上書き (ADR の空フォーム)
docs/adr/README.md
docs/architecture/README.md
docs/architecture/cheatsheet.md
docs/design/README.md
```

> ひな形 (空フォーム) は `docs/adr/` 等のコンテンツ列に置かず `docs/_templates/` に隔離する。これで「ひな形か実ドキュメントか」がパスで判別でき、誤認・誤編集を防ぐ。`/adr-new` はこの `_templates/adr.md` を読んで採番展開する。

### 3. 結果サマリ
- 作成したファイル一覧
- スキップしたファイル一覧 (既存があった場合)
- 次のアクション提案:
  - `/adr-new <title>` で最初の ADR を作成
  - `docs/architecture/0-context.md` から C4 図を書き始める

### 4. (任意) git add
ユーザーに確認の上、新規作成ファイルを `git add docs/` する。コミットは行わない。

## 注意

- agent-rules リポが見つからない場合はエラー (~/CLAUDE.md の symlink 経由でルートを推定するロジックも可)
- 既存 `docs/` 配下の構造が異なる場合は警告を出してから処理続行
