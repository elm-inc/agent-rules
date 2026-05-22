---
name: linear-status
description: Linear の Project / Issue / cycle の現状を表示する。今どんなプロジェクトが走っているか、自分のアサインは何か、cycle のゴールはどこかを 1 画面で確認したいときに使用
argument-hint: [--project <name>] [--mine] [--cycle]
disable-model-invocation: false
allowed-tools: mcp__linear__* Read Bash(git *) Bash(cat *)
---

# Linear 状況ブリーフィング

Linear に乗っているプロジェクト・課題・cycle の現状を 1 画面に集約して表示する。`/status` の Linear 版。

## 前提

Linear MCP が `claude mcp add --transport http --scope user linear https://mcp.linear.app/mcp` で登録され、`/mcp` で OAuth 認証済であること。未登録なら以下を案内して中断する:

```
Linear MCP が未登録です。以下を実行してください:
  claude mcp add --transport http --scope user linear https://mcp.linear.app/mcp
  /mcp linear  # OAuth 認証
```

> 旧 `--transport sse https://mcp.linear.app/sse` は 2026-04-08 で deprecated。既存 SSE 登録があれば `claude mcp remove linear -s user` してから上記で再登録する。

## 引数の解釈

- `--project <name|id>`: 特定 Project に絞る (部分一致)
- `--mine`: 自分にアサインされた Issue のみ
- `--cycle`: 現 cycle の Issue を表示
- 引数なし: デフォルト (現 cycle + 自分のアクティブ Issue + 進行中の Project)

## 実行手順

### 1. ワークスペース情報の取得
- `list_teams` 相当の MCP ツールで自分が所属する team 一覧
- `get_user` 相当で自分の user ID を取得 (mine フィルタ用)

### 2. データ取得 (並列)
- **Projects (active)**: status が `started` / `planned` の Project 一覧
- **Cycle (current)**: 各 team の現 cycle (`isActive=true`)
- **Issues**:
  - `--mine`: assignee=self の Issue
  - `--cycle`: 現 cycle に紐づく Issue
  - デフォルト: state=Started/In Progress の Issue (全 team)

### 3. ローカル状態との突き合わせ
- カレントリポの `parallel-tasks.json` を読む (`git rev-parse --git-common-dir` 経由)
- 各 task の `linear_issue_id` フィールドがあれば Linear Issue と紐付けて表示
- 紐付けが無い worktree タスクは「Linear 未紐付」として警告

### 4. 出力フォーマット

セクションに情報がなければ省略する。

```markdown
# 📅 Linear 状況 (<today>)

## 🎯 進行中の Project
| Project | Progress | 期日 | Lead |
|---|---|---|---|
| apps/batch test refactor | 5/6 | 2026-05-31 | @user |

## 🔄 現 Cycle (<team>: <cycle name> <start>〜<end>)
| Issue | Status | Assignee | Updated |
|---|---|---|---|
| ELM-106 | In Progress | @user | 2h ago |

## 👤 自分の Issue (active)
| ID | Title | Project | State | Priority |
|---|---|---|---|---|
| ELM-106 | Phase 6 state leak 解消 | test refactor | In Progress | 中 |

## 🌳 ローカル worktree との対応
| worktree | Linear | 状態 |
|---|---|---|
| test-refactor-phase6-state-leak | ELM-106 | ✅ 同期 |
| feat-foo | (未紐付) | ⚠ Linear に Issue が無い |

## ⚠ 警告
- (Issue が "In Progress" のまま 7 日以上動きが無いものを警告)
- (Linear に Done だが worktree が active のままのものを警告)
```

### 5. サマリと次アクションの提案

最後に 1-2 行で:
- 「今 cycle で残ってる Issue は N 件、期日まで X 日」
- 「Linear と worktree の同期が崩れている箇所があれば優先確認」

## 注意事項

- MCP API のレート制限に当たったらキャッシュなしで失敗を明示
- 表示は 1 画面 (各セクション 5 行以内) に抑える
- 詳細は「`/linear-status --project <name>` で絞り込める」とヒントを付ける
- `parallel-tasks.json` が無いリポでも MCP 情報だけは出す (worktree セクションを省略)
