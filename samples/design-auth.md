# 設計: ユーザー認証システム リニューアル

## 背景

既存の自社実装セッション管理を OAuth2 ベースに刷新する。レガシー DB の `sessions` テーブルを廃止し、JWT トークン + Redis セッションストアに移行。

## 要件

- 既存ユーザー (10万人) はメールアドレス + パスワードでログイン可
- Google / GitHub の OAuth でも認証可
- セッションは Redis に保存 (TTL 30 分)
- トークンは JWT (HS256, 24 時間有効)

## アーキテクチャ

```
[Client] → [API GW] → [Auth Service] → [Redis]
                          ↓
                    [User DB (Postgres)]
```

## 移行計画

1. 新 Auth Service デプロイ (旧 sessions テーブルと並行稼働)
2. 新規ログイン時は新しい JWT 発行
3. 既存セッションは sessions テーブルから読む (互換層)
4. 1 ヶ月後、互換層を削除

## セキュリティ

- パスワードは bcrypt (cost=12)
- JWT 署名鍵は環境変数に保存
- HTTPS のみ受付
- ログにトークンや PII を出力しない

## モニタリング

- Auth Service の latency と error rate を Grafana で監視
- 24 時間以内のログイン試行回数を Redis でカウント、100 回超でブロック
