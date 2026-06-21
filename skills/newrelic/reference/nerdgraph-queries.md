# NerdGraph クエリ断片 (reference)

`/newrelic` skill が使う GraphQL。エンドポイントは profile.region で切替:
US `https://api.newrelic.com/graphql` / EU `https://api.eu.newrelic.com/graphql`。
認証は HTTP ヘッダ `API-Key: <User Key NRAK-*>`。文字列は GraphQL 変数で渡し、
エスケープ事故と argv 漏洩を避ける。

## whoami — 鍵の持ち主

```graphql
{ actor { user { id name email } } }
```

## account 可視性検証 (doctor の中核)

`account(id:)` が null を返すなら、その鍵はそのアカウントを見られない = profile の
account_id か鍵の権限の取り違え。doctor / whoami で必ず確認する。

```graphql
query($id:Int!){ actor { account(id:$id){ id name } } }
```

## NRQL 実行

`Nrql` は custom scalar。変数で渡す。

```graphql
query($id:Int!,$q:Nrql!){ actor { account(id:$id){ nrql(query:$q){ results } } } }
```

## エンティティ検索 (entitySearch)

```graphql
query($q:String!){ actor { entitySearch(query:$q){
  results { entities { guid name entityType reporting } } } } }
```
例の検索式: `name LIKE '%api%' AND type = 'APPLICATION'` /
ダッシュボード: `type = 'DASHBOARD' AND accountId = <id>`

## アラートポリシー参照

```graphql
query($id:Int!){ actor { account(id:$id){ alerts {
  policiesSearch { policies { id name } } } } } }
```

## メモ / 検証項目

- **MCP のヘッダ名**: 公式リモート MCP (`https://mcp.newrelic.com/mcp/`) の認証ヘッダが
  NerdGraph と同じ `API-Key` か `Authorization: Bearer` かは NR のセットアップ手順で要確認
  (`templates/mcp.json.tmpl` のヘッダはこの検証後に確定する)。
- **レート制限**: NerdGraph は同時 25/user で 429。NRQL は 3,000 queries/account/min。
- **リージョン**: organization 作成時に確定し変更不可。EU 鍵は prefix `EU`。
