---
name: devlog
description: AI 開発の会話 (説明・依頼・調整・設計/テストの作り込み) を Claude Code の transcript から蒸留し、私的 dev-log に粒度別 (retro/summary/playbook/excerpt) で残す。良い型は抽象化して昇格。セッションの学びを残すときに使用
argument-hint: "retro | summary | playbook [--since <date>] | excerpt <題> | render <file>"
disable-model-invocation: false
allowed-tools: Bash(jq *) Bash(ls *) Bash(cat *) Bash(sed *) Bash(find *) Bash(wc *) Bash(mkdir *) Bash(test *) Bash(git *) Read Write Edit
---

# dev-log: AI 開発の会話ナレッジを残す

会話しながら開発する craft (どう説明し・どんな依頼をかけ・どう調整し・設計/テストをどう作り込むか) を、消える前に蒸留して残す。**会話は既に `~/.claude/projects/**/*.jsonl` に永続化されている**ので、それを読んで蒸留する。標準: [`docs/design/devlog-standard.md`](../../docs/design/devlog-standard.md) / 根拠: [`ADR-0016`](../../docs/adr/0016-devlog-knowledge-capture.md)。

## 機密 (最初に守る)

transcript には**顧客案件の内容が混ざる**。2 点を厳守:

1. **現プロジェクト以外の transcript を読まない** (別案件=顧客の会話。**fail-closed**。New Relic のテナント取り違え防止と同型)。`~/.claude/projects` 全体で最新の jsonl を掴む等の**横断フォールバックは禁止** — 別案件のセッションを誤って蒸留すると機密漏洩になる。
2. 生の dev-log は **`dev-log/` (gitignore・ローカル専用) にのみ書く**。public (agent-rules) に上げるのは、案件名・内部設計を**スクラブした抽象パターンだけ** (昇格時)。

## 引数

- `retro` (既定) → 現セッションを構造化レトロに
- `summary` → 現セッションを 3-5 行に
- `playbook [--since <date>]` → 期間横断で再利用可能な型を抽出 (抽象化)
- `excerpt <題>` → 技法を示す注釈付き会話抜粋
- `render <file>` → `/docs-publish` で PDF/Word 化 (抽象化済みのみ共有)

## 実行手順

### 1. transcript を特定 (現プロジェクトに限定・fail-closed)

```bash
PROJ=$(git rev-parse --show-toplevel 2>/dev/null || pwd)   # 現プロジェクトのルート
ENC=$(printf '%s' "$PROJ" | sed 's#[/.]#-#g')
DIR="$HOME/.claude/projects/$ENC"
FILE=$(ls -t "$DIR"/*.jsonl 2>/dev/null | head -1)          # 現セッション = 最新 mtime
```
- **現プロジェクトの `DIR` の中だけを対象にする**。`DIR` に無ければ「現プロジェクトの transcript が見つからない」とユーザーに確認する (session 起動 cwd と現 cwd がずれている等)。**`~/.claude/projects` 全体で最新を掴む横断フォールバックは禁止** (別案件=顧客の会話を誤って読むため・fail-closed)
- 期間横断 (`playbook`) も**現プロジェクトの `DIR` 内の複数 jsonl** に限定する

### 2. 会話ターンを抽出 (tool ノイズを落とす)

```bash
jq -rc 'select(.type=="user" or .type=="assistant")
        | {t:.timestamp, role:.message.role, text:.message.content}' "$FILE"
```
- 大きい (数 MB) ので、user 発話 + assistant のテキストに絞って読む。tool_use/tool_result の生ログは要点だけ

### 3. 標準に沿って蒸留

`docs/design/devlog-standard.md` のフォーマットで生成する。`retro` の必須節 (タスク/前提の説明の仕方/依頼の分解/調整の要所/設計の作り込み/テストの作り込み/詰まり所・効いた手/再利用できる型) を**空節を残さず**埋める。会話から読み取れない節は「該当なし」を明記 (捏造しない)。

### 4. 私的ストアに保存

```bash
mkdir -p dev-log
# 保存先 (gitignore 済み): dev-log/<YYYY-MM-DD>-<slug>.retro.md
```
- **必ず `dev-log/` (gitignore) に書く**。docs/ 等の追跡ディレクトリに書かない
- 既存があれば追記/更新。frontmatter (date/project/session/task) を必ず付ける

### 5. 昇格の判定 (任意)

retro の「再利用できる型」で横断再利用しそうなものは、**スクラブ (案件名・内部設計を除去) してから**ナレッジ昇格台帳 (`docs/notes/promotion-candidates.md`・ローカル) に候補記録する。2 回目で agent-rules へ昇格 (skill/rule/プレイブック doc)。判断・手順は CLAUDE.md「ナレッジ昇格ルール」。

### 6. 結果

保存したファイルパス・粒度・昇格候補の有無を提示。生 retro は私的である旨を明記。

## 注意

- **生ログを public に書かない** (機密混入)。共有は抽象化済みのみ
- 蒸留は会話から**読み取れた範囲**で。分からない節は捏造せず「該当なし」
- transcript が大きい場合はターン抽出で絞ってから読む (context 節約)
