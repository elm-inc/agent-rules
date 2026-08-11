# flow-diagram 雛形 (業務フロー図)

業務フロー図を標準スタイル + 必須情報で作るための雛形。標準: [`docs/design/flow-diagram-standard.md`](../../docs/design/flow-diagram-standard.md) / スキル: `/flow-diagram` / 根拠: [`ADR-0015`](../../docs/adr/0015-business-flow-diagram-standard.md)。

- `example.flow.md` — compliant なサンプル兼テンプレート。コピーして `<プロセス名>.flow.md` にし、frontmatter と Mermaid を差し替える
- 検証: `python3 scripts/lint-flow-diagram.py <file>.flow.md` (通るまで完成にしない)
- レンダリング確認: `/docs-publish`
- 案件リポでは `*.flow.md` を CI で lint する (雛形: `.github/workflows/flow-lint.yml`)
