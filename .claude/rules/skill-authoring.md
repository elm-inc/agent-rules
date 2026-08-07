---
paths:
  - "skills/**/SKILL.md"
---

# スキル作成規約 (agent-rules/skills)

このリポの `skills/*/SKILL.md` を編集・新規作成するときの規約。

- frontmatter: `name` / `description` (「いつ使うか」を具体的に書く ← Claude の自動起動判断に効く) / `argument-hint` / `disable-model-invocation` / `allowed-tools`。任意で `model` `effort`。
- **description は予算制**: 目安 ≤160 字で「何を / いつ使うか」に絞る。全 skill の description は毎セッション自動ロードされる「第 2 の CLAUDE.md」なので、冗長だと CLAUDE.md 刈り込みの成果を相殺する。
- **ニッチ/ハードウェア系スキルは `disable-model-invocation: true`**: ユーザーが明示起動する性質のもの (`rigol-dho804`・`webcam-jetson`・`atopile-view`・`mosh-clean` 等) は自動起動候補から外し、常時ロード対象からも除く。汎用的に自動起動させたいスキルのみ `false`。
- `allowed-tools` は space 区切り (comma も可、公式仕様)。**ツールはパスまで絞る**: `Bash(bash ~/repos/github.com/elm-inc/agent-rules/scripts/foo.sh*)` のように。`Bash(bash *)` は実質「任意コマンド許可」なので避ける。
- スクリプト/ファイル参照は canonical path の絶対パス (`~/repos/github.com/elm-inc/agent-rules/...`)。CLAUDE.md が clone 先をこのパスに規定している前提。
- `model`/`effort` を下げてよいのは「外部コマンド実行・整形が主」の軽量スキルのみ。合成・設計・判断が要るスキルは指定せず inherit (セッションモデル) のまま。
- 外部 LLM (Codex/DeepSeek/Gemini/ローカル Qwen) への委譲スキルは、起動保証・健全性確認・失敗時の代替案内をスキル本文に明記する。
- 実ロジック (スクリプト呼び出し等) を足したら実機で 1 回流してからコミットする。
