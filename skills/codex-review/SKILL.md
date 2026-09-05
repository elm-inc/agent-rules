---
name: codex-review
description: Codex CLI にコードレビューを依頼する。コードの変更内容をレビューしてほしい、Codex にレビューさせたい、セカンドオピニオンがほしいときに使用。--astra で GPT-6 Astra (フロンティア級・実費) に格上げして高リスク差分をレビューする
argument-hint: "[レビュー対象や追加指示（例: --base main, --uncommitted, --astra, セキュリティ観点で）]"
disable-model-invocation: false
allowed-tools: Bash(codex *) Bash(git *) Bash(*/codex-astra.sh *) Bash(*/frontier-usage.sh *)
---

# Codex CLI によるコードレビュー

Codex CLI の `review` サブコマンドを使ってコードレビューを実行する。
**多様性層** (groupthink 回避のため異ベンダーを 1 つ回す層) の実装視点担当。

## モデルの選択 — 既定は Sol、高リスクのみ Astra

| | モデル | コスト | いつ |
|---|---|---|---|
| 既定 | Codex CLI 管理 (GPT-5.6 Sol) | サブスク枠 | **通常の差分はこちら**。実装視点のセカンドオピニオン |
| `--astra` | **GPT-6 Astra** | **$10/$50 per MTok = 実費** | 高リスク変更 (セキュリティ・課金・データ破壊・公開 API・並行処理) のみ |

`--astra` は `scripts/codex-astra.sh` 経由で起動する (呼び出しをフロンティア枠の台帳に記録するため)。
**素の `codex --model gpt-6-astra` を直接叩かない** — 台帳に載らず、計器に穴が空く。

> 💰 **フロンティア枠**: Astra は Fable 5.1 と**同額・同じ $100/月 の共有予算**で、
> Astra 側には included 枠が無く**全量実費**。さらに**入力 272K 超で input 2x / output 1.5x** に
> なるため、リポ横断の広い差分に投げると跳ね上がる (横断は `/gemini-review` に残す)。
> 起動前に一言宣言し「なぜ Sol では不足か」を 1 行添える。根拠: [ADR-0019](../../docs/adr/0019-frontier-tier-orchestration.md)

> ⚠️ **Astra には Codex CLI 0.153.0 以上が必要**。0.149.1 は server-side で
> `400 "requires a newer version of Codex"` を返す。`codex-astra.sh` が事前にバージョンを見て
> 分かる形で止めるので、失敗したら `sudo npm install -g @openai/codex@latest` で更新する。

> 📊 **`--astra` の $ は台帳に載らない (0.153.4 実測)**。`codex review` には `--json` が無く、
> 権威ある usage (`turn.completed`) が出ないため、**呼び出し回数だけが記録され金額は不明**になる
> (statusline は `+` = 下限表示)。誤った数字を書くよりは未計上として正直に出す方針
> (ADR-0019)。金額の正は <https://platform.openai.com/usage> で確認する。

## 引数の解釈

`$ARGUMENTS` からまず `--astra` を抜き出し (あればモデルを格上げ)、残りを「**スコープ指定**」と「**カスタム指示**」に分けて読む。
**この 2 つは CLI 側で併用できない** (下の「CLI の制約」参照) ので、解釈もそれを前提にする:

1. **引数なし** → uncommitted な変更（staged + unstaged + untracked）をレビュー
2. **スコープ指定のみ** (`--uncommitted` / `--base <branch>` / `--commit <sha>`)
   → そのフラグ単独で実行する
3. **カスタム指示のみ** (フラグを含まないテキスト)
   → `codex review "<指示>"` で実行する。スコープは **uncommitted 既定**
4. **両方が混在** (例: `--base main セキュリティ観点で`)
   → **そのままでは実行できない。組み立てて失敗させないこと。**
   - `--uncommitted` との混在なら、既定スコープが同じなのでフラグを落として 3 の形にする
   - `--base` / `--commit` との混在は**どう書いても表現できない**ので、
     **ユーザーにどちらを優先するか確認する**
     (指示を捨ててスコープ単独で回すか / スコープを諦めて指示付き uncommitted で回すか)

## 実行手順

1. 現在の git 状態を `git status` と `git diff --stat` で確認し、レビュー対象を把握する
2. 引数から `--astra` の有無を判定する
   - **あり**: 高リスク変更の条件に該当するかを確認し、該当理由と「なぜ Sol では不足か」を一言宣言してから進む。
     該当しないのに `--astra` が付いていたら、実費である旨を伝えて Sol で回すことを提案する
   - **なし**: 通常どおり Sol で回す
3. 残りの引数を解釈して適切な `codex review` コマンドを組み立てる
4. 実行する（デフォルトは `--uncommitted`）
   - Sol: `codex review ...`
   - Astra: `./scripts/codex-astra.sh review ...` (agent-rules リポの scripts/ を指す)
5. Codex の出力をそのままユーザーに表示する
6. `--astra` を使った場合は、実行後に `scripts/frontier-usage.sh` で当月のフロンティア枠を確認して添える

## コマンド例

```bash
# uncommitted な変更をレビュー
codex review --uncommitted

# main ブランチとの差分をレビュー
codex review --base main

# 特定コミットをレビュー
codex review --commit abc1234

# カスタム指示付きレビュー (スコープは uncommitted 既定。フラグは付けられない)
codex review "セキュリティの観点でレビューしてください"

# --- 高リスク変更のみ: GPT-6 Astra に格上げ (実費・台帳記録あり) ---
./scripts/codex-astra.sh review --base main
./scripts/codex-astra.sh review "認証まわりの権限昇格を重点的に見てください"
```

## CLI の制約 (codex-cli 0.153.4 / 2026-09-06 実測)

- **`--uncommitted` / `--base` / `--commit` は 3 つとも PROMPT と併用できない。**
  渡すと `error: the argument '--uncommitted' cannot be used with '[PROMPT]'` で即失敗する。
  `Usage: codex review --uncommitted [PROMPT]` と表示されるのに排他という**上流 CLI 側の不整合**
- 素の `codex review "<指示>"` は動く。スコープは **uncommitted 既定**
- したがって「カスタム指示 + `--base` / `--commit`」は**現状どう書いても不可能**。
  ブランチ差分に観点を効かせたいなら、対象をコミットせずワークツリーに出すか、
  観点を諦めて `--base` 単独で回す

> 上流が直せば併用できるようになる性質の制約なので、**実測バージョンを併記してある**。
> 挙動が変わっていたらここを更新すること (`codex review --help` で確認)。
> **0.153.4 で再実測し、排他制約は依然として残っていることを確認済み** (2026-09-06)。

## 注意事項

- `codex review` は非インタラクティブに実行される
- 出力が長い場合でもすべて表示する
- レビュー結果に対して Claude 側から追加のコメントや要約を付けてもよい
- **モデル ID を直書きしない**。Astra の ID は `config/models.yml` の `frontier_diversity` が単一ソースで、
  スキルからは `codex-astra.sh` 経由でのみ触る (ADR-0017 の台帳原則)
- **多様性層は常時 1 つまで**。`--astra` を回した差分に、さらに `/deepseek-redteam` や
  `/gemini-review` を重ねない (2 つ回すコストに見合う追加検出は無い — ADR-0017)
