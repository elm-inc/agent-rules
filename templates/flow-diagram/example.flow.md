---
process: 経費申請の承認フロー
purpose: 従業員の経費申請を規程に沿って承認・精算する
owner: 経理部
actors:
  - 申請者
  - 承認者(上長)
  - 経理担当
systems:
  - 経費精算システム
trigger: 従業員が経費申請を提出したとき
version: "1.0"
updated: "2026-08-11"
---

# 経費申請の承認フロー

> これは agent-rules の**業務フロー図テンプレート兼サンプル**。`/flow-diagram` で生成し、
> `scripts/lint-flow-diagram.py` で標準準拠を機械検証する。標準: `docs/design/flow-diagram-standard.md`。
> 新規作成時はこのファイルをコピーして frontmatter と図を差し替える (`<プロセス名>.flow.md`)。

```mermaid
flowchart TD
  classDef exception fill:#fde2e2,stroke:#c0392b;
  classDef auto fill:#e8f0fe,stroke:#3b6fb0;

  subgraph 申請者
    S([開始: 申請提出]) --> A[経費申請を入力]
    A --> B[/領収書を添付/]
  end

  subgraph 経費精算システム
    B --> C{必須項目は揃っているか}
    C -->|いいえ| E1[差戻し通知]:::exception
    E1 --> A
    C -->|はい| D[(申請を登録)]:::auto
  end

  subgraph 承認者(上長)
    D --> F{承認するか}
    F -->|却下| G([終了: 却下])
    F -->|承認| H[承認を記録]
  end

  subgraph 経理担当
    H --> I{金額は規程内か}
    I -->|超過| J[追加確認を依頼]:::exception
    J --> F
    I -->|範囲内| K[精算処理]
    K --> Z([終了: 精算完了])
  end
```

## 補足 (任意記述欄)

- SLA / 所要時間: 申請提出から精算完了まで標準 5 営業日
- 例外の扱い: 差戻し (E1) と追加確認 (J) は `exception` クラスで明示
