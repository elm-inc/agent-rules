---
name: newrelic
description: New Relic を案件(=別顧客テナント)取り違えなく扱う。バッチ/CI/横断は NerdGraph 直の skill (profile 解決は fail-closed・呼び出し毎にアクティブ profile を echo・3者一致検証 doctor・監査ログ)。対話探索は per-project の公式リモート MCP を案内する。NRQL 実行・エンティティ/ダッシュボード/アラート参照・whoami 確認・案件 repo の init に使用
argument-hint: "<subcommand> | whoami | doctor | nrql \"<NRQL>\" | entities | dashboards | alerts | profile list|show|path | init [dir] --profile <名>"
disable-model-invocation: false
allowed-tools: Bash(uv *) Bash(cat *) Bash(ls *) Bash(test *) Bash(direnv *) Read Write
---

# New Relic 接続 (マルチテナント安全)

受託では案件ごとに**別顧客の New Relic テナント**を触る。間違ったテナントへのクエリは
**顧客データの混線**になる (gh の `_chd` サイレント切替事故と同型)。本スキルは
「いまどの顧客アカウントを見ているか」を常に**明示・検証可能**にし、暗黙の既定に
**倒さない (fail-closed)** ことを最優先する。

根拠: [ADR-0008](../../docs/adr/0008-newrelic-connection-hybrid.md) / 設計: [docs/design/newrelic-skill.md](../../docs/design/newrelic-skill.md)

## いつ skill / いつ MCP か (2経路・混同しない)

| 経路 | 認証 | 向き |
|---|---|---|
| **skill (本体・NerdGraph 直)** | profile (`~/.newrelic/<名>.env`) | ヘッドレス/バッチ/CI/**複数顧客横断**。`--profile` 明示でテナントを取り違えない。レート/リージョン/監査を完全制御 |
| **per-project 公式リモート MCP** | User Key (`NRAK-*`) / OAuth | **単一テナント repo の対話探索**。NRQL/ダッシュボード/アラートの NR メンテ tool surface が効く |

- **横断・共有 repo は MCP に頼らず skill の `--profile`** を呼び出し毎に使う (ADR §B)。
- per-project MCP は `/newrelic init` が `.newrelic-profile` から `.mcp.json` を**生成**する (手書き禁止)。**global には登録しない** (付け忘れ=接続不能で fail-closed、誤爆にしない)。
- MCP 接続後・不安時は **`/newrelic doctor`** で「MCP と skill が同一顧客を指す」ことを検証してから対話する。

## セットアップ (案件ごと)

1. 鍵を保管: `~/.newrelic/<profile>.env` を作成 (`templates/profile.env.tmpl` 参照)、**`chmod 600`**。
   `NEW_RELIC_API_KEY` / `NEW_RELIC_ACCOUNT_ID` / `NEW_RELIC_REGION`(us 既定/eu)。
2. 案件 repo で雛形展開: `/newrelic init --profile <名>` → `.newrelic-profile` + `.mcp.json` + `.gitignore`/`.envrc` を整備。
3. `direnv allow` (env バインド) → **`/newrelic doctor`** で3者一致 (region == profile == 鍵が見える account) を検証。
4. 以後、対話は MCP、バッチ/横断は `/newrelic nrql ...` など。

## サブコマンド

```
/newrelic whoami                     # 鍵が見える account/region を表示 (= gh auth status 相当)
/newrelic doctor                     # 3者一致検証 (.mcp.json/profile/鍵の指す account)
/newrelic nrql "SELECT count(*) FROM Transaction SINCE 1 hour ago"
/newrelic entities --query api --type APPLICATION
/newrelic dashboards                 # ダッシュボード一覧
/newrelic alerts                     # アラートポリシー参照
/newrelic profile list|show|path     # profile 一覧(名前のみ)/解決結果/パス
/newrelic init [dir] --profile <名>  # per-project 雛形展開
```

実行は `uv run skills/newrelic/scripts/newrelic.py <subcommand> ...` (PEP723、依存自動解決)。

## 安全規律 (ADR §A–G)

- **profile 解決は fail-closed**: `--profile` > repo の `.newrelic-profile` > **エラー**。空/不正/未知名・perms 緩・region 不正は即停止。暗黙の既定に倒さない。
- **鍵は argv に出さない** (`--profile` は名前のみ。鍵は profile ファイルから読む) → 履歴/プロセスリスト漏洩を防ぐ。
- **`.newrelic-profile`・`.envrc` は commit しない** (`.gitignore`)。顧客との取引関係が git 履歴に漏れる。profile 名も非識別的に。
- **全コマンドが冒頭に `[profile=… account=… region=…]` を echo**。破壊的操作前は再確認。
- **監査ログ** `~/.newrelic/audit.log` に呼び出し毎追記 (鍵・生 NRQL は記録せず NRQL は SHA-256)。
- リージョンは profile 単位 (US 既定・EU 切替)。EU 鍵 prefix と region の不一致は停止。

## トラブル時

- `profile を解決できません` → `--profile` 指定 or repo 直下に `.newrelic-profile`。
- `account NNN を見られません` → profile の `NEW_RELIC_ACCOUNT_ID` か鍵の権限を確認。
- doctor が `$NEW_RELIC_API_KEY` 未設定を指摘 → `direnv allow` (or `.envrc` を置く)。
- 機密性が高くクラウド送信を避けたい集計は、NRQL を絞る/対象 account を限定する。
