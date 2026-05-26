# agent-rules

`Claude Code` / `Codex CLI` で使う **ルール・スキル・テンプレートの単一ソース**。
各マシンの `~/CLAUDE.md`, `~/RULES.md`, `~/AGENTS.md`, `~/.claude/skills/*`, `~/.codex/skills/*`, `~/.codex/agent-rules.config.toml` は本リポへの symlink で同期する。

> 改善はこのリポへの PR で行い、各マシンは `git pull` + `install.sh` で同期する。

---

## クイックスタート

新マシンでのセットアップ:

**ghq を使う場合 (推奨):**

```bash
ghq get https://github.com/elm-inc/agent-rules
"$(ghq root)/github.com/elm-inc/agent-rules/install.sh"
```

**ghq が無い場合:**

```bash
git clone https://github.com/elm-inc/agent-rules ~/repos/github.com/elm-inc/agent-rules
~/repos/github.com/elm-inc/agent-rules/install.sh
```

`install.sh` は idempotent。既存 symlink はスキップ、不足分のみ追加する。配置先は任意で、`install.sh` 自身からの相対で symlink を貼るのでパスに依存しない。

### 前提

| 項目 | 要件 |
|---|---|
| OS | macOS / Linux (`bash` + `ln -s` が使えること) |
| Claude Code | 既にインストール済み (`~/.claude/skills/` を読みに行く) |
| Codex CLI | Codex で共通ルール・スキル・MCP 設定レイヤーを使う場合に必要 |
| `gh` CLI | `/status` で PR/Issue を集計したい場合に必要 |
| `git` | worktree 系スキルで必須 |

### 更新

ghq を使った場合:

```bash
cd "$(ghq root)/github.com/elm-inc/agent-rules"
git pull
./install.sh   # 新しいスキルが追加されていれば symlink される
```

`git clone` した場合 (clone 先のパスに合わせて):

```bash
cd ~/repos/github.com/elm-inc/agent-rules
git pull
./install.sh
```

symlink 経由なので、`git pull` した時点で `~/CLAUDE.md` 等の内容は自動的に最新になる。`install.sh` の再実行は **新しいスキルや新ファイルが追加されたとき** に必要。

> **注意:** `install.sh` は不足分の symlink を追加するだけで、**削除・リネームされたスキルの symlink は自動で消さない**。スキルが削除/リネームされた場合は dangling symlink が `~/.claude/skills/` や `~/.codex/skills/` に残るため、手動で `rm` する必要がある (詳細はトラブルシュート参照)。

---

## install.sh が貼る symlink

| symlink | リンク先 |
|---|---|
| `~/CLAUDE.md` | `<repo>/CLAUDE.md` |
| `~/RULES.md`  | `<repo>/RULES.md` |
| `~/AGENTS.md` | `<repo>/AGENTS.md` |
| `~/.claude/skills/<name>` | `<repo>/skills/<name>` (全スキル分) |
| `~/.codex/skills/<name>` | `<repo>/skills/<name>` (全スキル分) |
| `~/.codex/*.config.toml` | `<repo>/.codex/*.config.toml` |

既に同名のファイル (symlink でない実体) がある場合は WARN を出してスキップする。手動で退避してから再実行する。

`~/.codex/config.toml` はモデル設定、認証状態、プロジェクト trust 設定などの個人・マシン依存情報を含むため、`install.sh` では上書きも symlink 化もしない。共有 MCP 定義や共有 feature flag は `<repo>/.codex/*.config.toml` に置き、Codex 起動時に `--profile-v2 agent-rules` 等を付けて読み込む。

---

## ディレクトリ構成

```
agent-rules/
├── CLAUDE.md         # Claude Code 用の上位ルール (~/CLAUDE.md にリンク)
├── AGENTS.md         # Codex CLI 用の上位ルール (~/AGENTS.md にリンク)
├── RULES.md          # ツール横断の共通ルール (~/RULES.md にリンク)
├── .codex/           # Codex CLI 用の共有 config profile / MCP fragments
├── install.sh        # symlink を貼る idempotent スクリプト
├── skills/           # Claude Code skill 群 (各ディレクトリが 1 skill)
├── templates/        # 各リポにコピーして使う雛形 (docs/ 構造など)
└── prompts/          # 人間がコピペする想定のプロンプト集
```

### ファイルの役割

- **`RULES.md`** — Claude Code / Codex CLI 共通の原則 (言語、Git、セキュリティ、禁止事項、テスト等)。`CLAUDE.md` と `AGENTS.md` の冒頭でこのファイルを読むよう指示している
- **`CLAUDE.md`** — Claude Code 専用の上位ルール。Codex 連携・並列開発・ドキュメント方針などを定義
- **`AGENTS.md`** — Codex CLI 専用の上位ルール (現状は最小限)
- **`.codex/*.config.toml`** — Codex CLI の共有 config layer。MCP 定義などを置き、`codex --profile-v2 agent-rules` 等で読み込む

---

## スキル一覧

`~/.claude/skills/` と `~/.codex/skills/` に symlink されることで、Claude Code / Codex CLI から同じ skill 定義を参照できる。

Codex CLI で共有 config layer も使う場合:

```bash
codex --profile-v2 agent-rules
codex exec --profile-v2 agent-rules "依頼内容"
```

MCP を共有管理したい場合は `.codex/agent-rules.config.toml` に `[mcp_servers.<name>]` を追加する。シークレット値は直接書かず、`env_vars = ["TOKEN_NAME"]` や `bearer_token_env_var = "TOKEN_NAME"` で環境変数名だけを共有する。

Codex 向けの詳細な運用・検証手順は [`docs/setup/codex-cli.md`](docs/setup/codex-cli.md) を参照。

補助スクリプト:

| スクリプト | 用途 |
|---|---|
| `scripts/codex-agent-rules` | `--profile-v2 agent-rules` 付きで Codex を起動 |
| `scripts/codex-doctor.sh` | symlink / TOML / MCP env var / dangling skill link を確認 |
| `scripts/validate-codex-skills.sh` | Codex skill として最低限の frontmatter を確認 |
| `scripts/render-codex-config.sh` | profile と MCP fragment を連結して確認 |

Codex plugin / marketplace で配布したい場合の最小 scaffold として `plugins/agent-rules/` と `.agents/plugins/marketplace.json` も置いている。現時点の推奨インストール経路は引き続き `install.sh` による symlink。

### Codex CLI 連携
| スキル | 用途 |
|---|---|
| `/codex-review` | 差分 (uncommitted / `--base`) をレビュー依頼 |
| `/codex-audit` | プロジェクト全体の網羅的レビュー |
| `/codex-task` | 修正・実装タスクを Codex に委譲 |

### 並列開発 (git worktree)
| スキル | 用途 |
|---|---|
| `/worktree-start` | worktree 作成 + タスクをレジストリに登録 |
| `/worktree-list` | 全タスクの状況・衝突リスクを表示 |
| `/worktree-finish` | ベースブランチへマージ + worktree 削除 |

タスク情報は `<repo>/.git/parallel-tasks.json` に記録され、複数 worktree から共有参照できる。

### ドキュメント
| スキル | 用途 |
|---|---|
| `/docs-init` | `docs/{adr,architecture,design}` の標準構造を新規プロジェクトに展開 |
| `/docs-visualize` | C4 model + 状態機械 + シーケンス図で可視化 (Mermaid) |
| `/adr-new <タイトル>` | 通し番号自動採番で ADR を作成 |

### 状況把握
| スキル | 用途 |
|---|---|
| `/status` | 最近のコミット・open PR/Issue・worktree タスク・project memory・未コミット変更を一覧 |

各スキルの詳細は `skills/<name>/SKILL.md` を参照。

---

## テンプレート

`templates/docs/` に各リポへ展開する `docs/{adr,architecture,design}` の雛形がある。`/docs-init` がここからコピーする (既存ファイルは上書きしない)。

詳細は [`templates/docs/README.md`](templates/docs/README.md) を参照。

---

## プロンプト集

`prompts/` には **人間が手動でコピペして使う** プロンプト雛形を置く (スキルとは別物)。新プロジェクトでのオンボーディング時など、スキルの自動 invoke に頼らず明示的に指示したい場面で利用する。

詳細は [`prompts/README.md`](prompts/README.md) を参照。

---

## 改善フロー

1. ローカルで変更 (新スキル追加、ルール改訂、テンプレ修正など)
2. **`/codex-review`** で Codex にレビュー依頼 (uncommitted 対象)
3. 重大な指摘があれば修正
4. Conventional Commits 形式 + 日本語メッセージでコミット
5. PR を出す
6. マージ後、各マシンで `git pull` (+ 新スキル追加時は `./install.sh`)

大きな方針変更は ADR (`docs/adr/`) として残す。

---

## トラブルシュート

### `install.sh` が WARN を出してスキップする
`~/CLAUDE.md` 等が **symlink ではない実体ファイル** として既に存在している。退避してから再実行:

```bash
mv ~/CLAUDE.md ~/CLAUDE.md.bak
~/repos/github.com/elm-inc/agent-rules/install.sh
```

### スキルが Claude Code から見えない
- `~/.claude/skills/<name>` が symlink になっているか確認: `ls -la ~/.claude/skills/`
- Claude Code を再起動 (新規スキルは起動時に読み込まれる)

### スキルが Codex CLI から見えない
- `~/.codex/skills/<name>` が symlink になっているか確認: `ls -la ~/.codex/skills/`
- Codex CLI を再起動 (新規スキルは起動時に読み込まれる)

### Codex の共有 MCP 設定を使いたい
`~/.codex/agent-rules.config.toml` が symlink になっているか確認し、Codex 実行時に `--profile-v2 agent-rules` を付ける。`--profile-v2` は runtime command 用なので、`codex mcp list` などの管理コマンドには適用されない:

```bash
codex --profile-v2 agent-rules
codex exec --profile-v2 agent-rules "MCP が使えるか確認して"
```

### symlink が別の場所を指している
`install.sh` は **既存 symlink を上書きしない**。意図的にやる場合は手動で `rm` してから再実行。

### 削除/リネームされたスキルの symlink が残っている
`install.sh` は不足分を追加するのみで、**obsolete な symlink の削除は行わない**。リンク先が消えた dangling symlink を一掃するには:

```bash
# dangling symlink (リンク先が存在しないもの) を列挙
find ~/.claude/skills -maxdepth 1 -type l ! -exec test -e {} \; -print

# 問題なければ削除
find ~/.claude/skills -maxdepth 1 -type l ! -exec test -e {} \; -delete
```

Codex 側も同様:

```bash
find ~/.codex/skills -maxdepth 1 -type l ! -exec test -e {} \; -print
find ~/.codex/skills -maxdepth 1 -type l ! -exec test -e {} \; -delete
```
