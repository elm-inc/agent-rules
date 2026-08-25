---
name: devlog
description: Claude Code の会話 (transcript) を蒸留して私的 dev-log に残す。retro/summary/playbook/excerpt に加え、teach で「実際の依頼文をそのまま見せる教材」を作る。セッションの学びを残したい・他の人に頼み方を教えたいときに使用
argument-hint: "retro | summary | playbook [--since <date>] | excerpt <題> | teach [読者] | render <file>"
disable-model-invocation: false
allowed-tools: Bash(python3 /home/elmo/repos/github.com/elm-inc/agent-rules/scripts/transcript-extract.py*) Bash(jq *) Bash(ls *) Bash(cat *) Bash(sed *) Bash(find *) Bash(wc *) Bash(mkdir *) Bash(test *) Bash(git *) Read Write Edit
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
- `excerpt <題>` → 技法を示す注釈付き会話抜粋 (1 技法の断片)
- `teach [読者]` → **1 セッションを教材化**。実際の依頼文を verbatim で見せ、各発話が何を起こしたかを注釈する (既定の読者: 非エンジニアのメンバー)
- `render <file>` → `/docs-publish` で PDF/Word 化 (抽象化済みのみ共有)

> `excerpt` と `teach` の違い: `excerpt` は「1 つの技法を示す断片」、`teach` は「1 セッション全体を、指定した読者が真似できる形に組み直した教材」。

## 実行手順

### 1. transcript を特定 (現プロジェクトに限定・fail-closed)

```bash
EXTRACT=~/repos/github.com/elm-inc/agent-rules/scripts/transcript-extract.py
python3 "$EXTRACT" list        # 現プロジェクトの transcript を確認 (無ければ非 0 で止まる)
```

抽出器が現プロジェクトのディレクトリだけを見る (横断フォールバックを実装していない)。見つからないときは自分でパスを組み立てて探しに行かず、ユーザーに確認する。
- **現プロジェクトの中だけを対象にする**。`~/.claude/projects` 全体で最新を掴む横断フォールバックは禁止 (別案件=顧客の会話を誤って読むため・fail-closed)
- 期間横断 (`playbook`) は `--all-sessions` で現プロジェクトの複数 jsonl に限定して広げる

### 2. 会話ターンを抽出 (tool ノイズを落とす)

```bash
python3 "$EXTRACT" turns      # 人間が書いた発話だけ (スキル展開・コマンド出力を除外)
python3 "$EXTRACT" choices    # AskUserQuestion の質問と、実際に選ばれた回答
python3 "$EXTRACT" stats      # 発話数・文字数・ツール実行回数 (教材の実数はここから取る)
```

- transcript は数 MB あるので、**生の jsonl を読み下さない**。上の 3 つで足りる
- 🔒 **自分の出力を再取り込みしない**: transcript を読むコマンドの出力自体が transcript に記録される。`"質問"="回答"` のような**テキスト一致で拾うと、過去の抽出結果を人間の発言として二重に数える** (実測: 8 対が 16 対に化けた)。`choices` は `tool_use_id` で構造的に辿ってこれを避けている。自前で jq を書き足すときも同じ罠を踏まないこと

### 3. 標準に沿って蒸留

`docs/design/devlog-standard.md` のフォーマットで生成する。`retro` の必須節 (タスク/前提の説明の仕方/依頼の分解/調整の要所/設計の作り込み/テストの作り込み/詰まり所・効いた手/再利用できる型) を**空節を残さず**埋める。会話から読み取れない節は「該当なし」を明記 (捏造しない)。

### 3b. `teach` のときの作り方 (他の粒度と違う点)

読者が**自分でも同じことを頼めるようになる**ことがゴール。だから要約ではなく **実際の依頼文をそのまま見せる**。

1. **人間の発話は verbatim**。整形も要約もしない。**誤字もそのまま残す** (「それでも伝わった」ことが読者の不安を減らす)
2. 各発話に 3 点を添える: **何が起きたか / なぜ効いたか / 真似するときの注意**
3. `choices` の結果を「**選ぶだけで済んだ判断**」として表に出す。読者が一番誤解するのは「全部指示しないといけない」なので、ここが効く
4. 数値 (発話数・文字数・ツール実行回数) は `stats` の実測を使う。**手で数えない・盛らない**
5. 「**やらなくてよかったこと**」の節を必ず置く (設計の指定・技術選定・コマンドの暗記など、読者が身構えている項目を明示的に外す)
6. うまくいかなかった箇所も落とさない。中断 (`⏸`) や言い直しは steering の実例として価値がある

保存先: `dev-log/<YYYY-MM-DD>-<slug>.teach.md`

> **案件名の扱い**: 既定は **transcript のまま** (共有相手が顧客情報を見てよい社内メンバーである前提)。社外・不特定に配る場合はこのモードの出力をそのまま使わず、スクラブしてから渡す。匿名化は将来オプション化する。

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

- **生ログを public に書かない** (機密混入)。agent-rules 等の追跡リポに出力しない
- `teach` の出力は**社内共有を想定した生テキスト**。配布前に読み手の範囲を確認する
- 蒸留は会話から**読み取れた範囲**で。分からない節は捏造せず「該当なし」
- transcript が大きい場合はターン抽出で絞ってから読む (context 節約)
