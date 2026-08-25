# dev-log 標準 (AI 開発の会話ナレッジ)

Claude Code で会話しながら開発する際の **craft** (どう説明し・どんな依頼をかけ・どう調整し・設計/テストをどう作り込むか) を、消える前にログとして残し、必要な粒度で出すための標準。スキル: `/devlog` / 根拠: [`ADR-0016`](../adr/0016-devlog-knowledge-capture.md)。

## ソース: 会話は既に永続化されている

Claude Code はセッション全文を `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` に永続化している (role・内容・model・usage・timestamp)。**新たにログ機構を作る必要はなく、これを蒸留する**。

- encoded-cwd: `pwd | sed 's#[/.]#-#g'` (例 `-home-elmo-repos-github-com-elm-inc-agent-rules`)
- 現セッション: そのディレクトリの最新 mtime の `*.jsonl`
- 会話ターン抽出 (tool ノイズを落とす):
  ```bash
  jq -rc 'select(.type=="user" or .type=="assistant") | {t:.timestamp, role:.message.role, text:(.message.content)}' <file>.jsonl
  ```

## 機密 (最重要)

transcript には**顧客案件の内容が混ざる**。よって:

- **生の dev-log は私的**: `dev-log/` (gitignore・ローカル専用) or 別 private repo。**public に出さない** (台帳・design-registry と同じ「私的な生 + 公開の抽象」)
- agent-rules (public) に載せてよいのは、**案件名・内部設計を落とした抽象化された craft パターンだけ** (昇格時にスクラブ)

## 粒度 (必要な粒度でアウトプット)

| 粒度 | 対象 | 用途 |
|---|---|---|
| `summary` | 1 セッション | 3-5 行の要約 (何を・どうやって・結果) |
| `retro` | 1 セッション | 構造化レトロ (下記フォーマット)。**主力** |
| `playbook` | 期間横断 | 再利用可能なプロンプト/依頼/設計/テストの型を抽出 (抽象化) |
| `excerpt` | 任意 | 技法を示す注釈付き会話抜粋 (1 技法の断片) |
| `teach` | 1 セッション | 指定した読者が真似できる教材。**実際の依頼文を verbatim で見せる** |

## retro フォーマット (記載漏れ防止)

保存先: `dev-log/<YYYY-MM-DD>-<slug>.retro.md` (私的)。frontmatter 必須 + 以下の節を埋める (空節は残さない):

```markdown
---
date: 2026-08-11
project: <リポ名 or 案件>
session: <transcript ファイル or session-id>
task: <一行で: 何を達成しようとしたか>
---

## タスク / 目的
## 前提の説明の仕方        # 状況・制約をどう伝えたか
## 依頼の分解              # ゴールをどう分けて依頼したか
## 調整 (steering) の要所   # どこで方向を直したか・その理由
## 設計の作り込み          # 設計を会話でどう固めたか (redteam/代替案の使い方 等)
## テストの作り込み        # テスト観点・検証をどう作ったか
## 詰まり所 / 効いた手・効かなかった手
## 再利用できる型 (playbook 昇格候補)   # 抽象化して agent-rules に上げられるか
```

## teach フォーマット (教材)

保存先: `dev-log/<YYYY-MM-DD>-<slug>.teach.md` (私的)。読者が**自分でも同じことを頼めるようになる**のがゴールなので、要約ではなく**実際の依頼文をそのまま**載せる。

```markdown
---
date: 2026-08-25
project: <リポ名 or 案件>
session: <transcript ファイル or session-id>
audience: <読者。既定: 非エンジニアのメンバー>
source: transcript (人間の発話は verbatim)
---

## 何ができたか            # 成果物と、人間が費やした入力量の実数
## 人間が書いた全文        # verbatim。1 発話ごとに「何が起きたか / なぜ効いたか / 注意」
## 選ぶだけで済んだ判断    # AskUserQuestion の質問と選んだ答えの表
## 依頼の型               # そのまま流用できる言い方
## やらなくてよかったこと  # 設計指定・技術選定・コマンド暗記など、読者が身構えている項目
## つまずいた所と、その時の言い方   # 中断・言い直しも落とさない
```

**守ること**:

- **人間の発話は verbatim。誤字も直さない** — 「それでも伝わった」が読者の不安を下げる。整形すると「うまい依頼文でないと動かない」という逆のメッセージになる
- **数値は `transcript-extract.py stats` の実測**。手で数えない・盛らない
- 中断や言い直しを消さない (steering の実例)
- 案件名は既定でそのまま。社外に配るならスクラブしてから渡す

## 昇格パス (agent-rules へ)

retro の「再利用できる型」で横断再利用しそうなものは、**スクラブ (案件名・内部設計を除去) してから**ナレッジ昇格台帳 (`docs/notes/promotion-candidates.md`・ローカル) に候補記録し、2 回目で agent-rules の skill / rule / プレイブック doc へ昇格する ([ADR-0013] と同じ 2 回目ルール)。private な生 retro はローカルに残す。

## タイミング (適時)

- **オンデマンド**: `/devlog retro` を区切りで実行
- **Stop hook**: セッション終了時に「学びが多ければ /devlog を検討」と促す (templates/claude-settings)
- **週次ロールアップ** (任意): 最近の transcript を走査し playbook を更新

## レンダリング

人間共有が要るときは `/docs-publish` で Markdown → PDF/Word (機密を含む生 retro は共有しない。共有は抽象化済みのものだけ)。
