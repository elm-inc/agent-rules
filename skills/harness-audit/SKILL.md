---
name: harness-audit
description: 全リポの機密区分 (.harness.yml の sensitivity) の案を出し、確認のうえローカル宣言を一括で書く。未宣言 repo が多い・外部送信の警告が多いときに使用
argument-hint: "[--gh] (GitHub の公開状態を案に使う)"
disable-model-invocation: false
allowed-tools: Bash(python3 ~/repos/github.com/elm-inc/agent-rules/scripts/harness.py *) Read
---

# 機密区分の一括付け (ADR-0023)

外部 LLM への送信は、repo の機密区分 (`public` / `internal` / `confidential`) に照らして**送信の前に伝える** (遮断はしない)。区分が**未宣言の repo は confidential と同じ扱い**なので、宣言が無いままだと送信のたびに警告が出る。このスキルで全 repo の区分を一度に付ける。

- 区分の案は機械が出すが、**最終判断はユーザー**
- 書き込むのは**ローカル宣言** (`~/.config/agent-rules/harness/<host>/<org>/<repo>.yml`) だけ。各 repo の作業ツリーは汚さない
- 案とローカル宣言は案件名を含むため**ローカル専用** (agent-rules にコミットしない)

## 実行手順

### 1. 案を作る

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/scripts/harness.py audit propose        # 引数に --gh があれば付ける
```

- 既存の宣言がある repo はその区分を案にする
- `--gh` を付けると、GitHub で公開されている repo を `public` と提案する (gh の認証が無い org は非公開扱い)
- それ以外は `confidential` を提案する。社内だけのもの (個人・自社ツール等) は `internal` に下げてもらう

### 2. ユーザーに確認してもらう

案のファイル (`~/.config/agent-rules/harness/proposal.yml`) を Read し、**区分ごとの件数と、confidential 以外を提案した repo の一覧**をユーザーに見せる。

- 「internal に下げたい repo」「public にしたい repo」を聞き、ユーザーの指示どおりに `proposal.yml` の `sensitivity` を書き換える (Edit はユーザーが指示した行だけ)
- 迷う repo は confidential のままにする (警告が出るだけで作業は止まらない)

### 3. 一括で書く (ユーザーの確認後)

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/scripts/harness.py audit apply
```

既存のローカル宣言にある他のキー (`stack:` 等) は保持し、`sensitivity` だけを更新する。

### 4. 結果

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/scripts/harness.py status
```

未宣言の repo が 0 件になったこと (何も出なければ平時) を確認して報告する。repo に `.harness.yml` をコミットして共有したい自社 repo は、repo ごとの PR として別に行う。

## 注意

- 区分の解決は「repo の `.harness.yml` とローカル宣言のうち**厳しい方**」。ローカル宣言で区分を下げても、repo 側が confidential なら confidential のまま
- 本当に送信を止めたいときの非常口は従来どおり (`DEEPSEEK_API_KEY=` / `GEMINI_API_KEY=` を明示的に空にしてスキルを呼ぶ)
