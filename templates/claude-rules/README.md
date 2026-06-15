# `.claude/rules/` — パススコープルール (Claude Code 公式機能)

CLAUDE.md が肥大化したら、ファイル種別/ディレクトリ単位の指示を `.claude/rules/*.md` に切り出す。
`paths:` を付けると **Claude が該当ファイルを読んだ時だけ**ロードされ、常時の文脈消費を減らせる。
公式: [memory#organize-rules-with-claude/rules/](https://code.claude.com/docs/en/memory)

## 使い分け (CLAUDE.md / rules / skills)

| 仕組み | ロード | 用途 |
|---|---|---|
| **CLAUDE.md** | 全セッション常時 (<200 行に保つ) | 常に要る事実: ビルドコマンド・規約・構成・「常に X」 |
| **`.claude/rules/` (`paths:` 付き)** | 該当ファイル読込時のみ | 特定種別でだけ要る規約 (API 規約・テスト規約・言語別スタイル) |
| **skills (`/name`)** | 呼んだ時 / 関連と判断時 | 多段手順・チェックリスト |

`paths` 無しの rule は `.claude/CLAUDE.md` と同等で常時ロードされる (CLAUDE.md の分割用)。

## 形式

`<project>/.claude/rules/<topic>.md` に置く (サブディレクトリ可、`.md` を再帰探索)。

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "src/**/*.{ts,tsx}"   # brace 展開・複数パターン可
---

# API 開発ルール
- 全エンドポイントで入力検証を必須にする
- 標準エラーレスポンス形式を使う
```

glob 例: `**/*.ts` (全 TS) / `src/**/*` (src 配下全部) / `*.md` (ルートの md) / `src/components/*.tsx`。

## 共有・スコープ

- **symlink で複数プロジェクト共有**: `ln -s ~/shared-claude-rules .claude/rules/shared`
- **ユーザーレベル** `~/.claude/rules/*.md` は全プロジェクトに適用 (project rule より低優先)

## 本リポでの実例

agent-rules 自身が `.claude/rules/shell-scripts.md` (`scripts/*.sh`) と
`skill-authoring.md` (`skills/**/SKILL.md`) を採用。編集時にだけ規約が文脈に載る生きた例。
