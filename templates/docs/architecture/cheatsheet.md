# Mermaid Cheatsheet

drive-partner / 他プロジェクトでよく使う Mermaid 記法の早見表。

## C4 Context (L1)

```mermaid
C4Context
    title System Context

    Person(user, "ユーザー", "説明")
    System(myApp, "MyApp", "メインシステム")
    System_Ext(external, "外部 API", "...")

    Rel(user, myApp, "操作")
    Rel(myApp, external, "HTTPS")
```

## C4 Container (L2)

```mermaid
C4Container
    title Container Diagram

    Person(user, "ユーザー")
    System_Ext(api, "外部 API")

    Container_Boundary(app, "MyApp") {
        Container(ui, "UI Layer", "SwiftUI", "...")
        Container(core, "Core", "Swift", "...")
        ContainerDb(store, "DB", "SQLite", "...")
    }

    Rel(user, ui, "")
    Rel(ui, core, "")
    Rel(core, store, "")
    Rel(core, api, "HTTPS")
```

## C4 Component (L3)

```mermaid
C4Component
    title Component Diagram

    Container_Boundary(b, "Boundary") {
        Component(a, "A", "Swift", "...")
        Component(b2, "B", "Swift", "...")
    }
    Rel(a, b2, "uses")
```

## 状態機械

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> running: start
    running --> idle: stop
    running --> error: failure
    error --> idle: reset
```

## シーケンス

```mermaid
sequenceDiagram
    actor U as ユーザー
    participant A as ComponentA
    participant B as ComponentB

    U->>A: 操作
    A->>B: 委譲
    B-->>A: 応答
    A-->>U: 表示
    Note over A,B: 補足
```

## フローチャート (依存・データフロー)

```mermaid
flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Action]
    B -->|No| D[Other]
    C --> E[End]
    D --> E
```

## クラス図 (必要時のみ)

```mermaid
classDiagram
    class Foo {
        +String name
        +action()
    }
    class Bar
    Foo --> Bar : uses
```

## ER 図 (DB 構造)

```mermaid
erDiagram
    USER ||--o{ POST : writes
    USER {
        UUID id
        string name
    }
    POST {
        UUID id
        UUID user_id
        string title
    }
```

## Tips

- GitHub の PR / Issue / README で **そのままレンダリング** される
- 描画が崩れる場合は VS Code の Mermaid プレビューで確認
- 複雑になりすぎたら **図を分割** するか D2 への移行を検討
