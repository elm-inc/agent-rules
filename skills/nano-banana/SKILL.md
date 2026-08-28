---
name: nano-banana
description: Nano Banana 2 (Gemini の画像モデル) でテキストから画像を生成し、参照画像を渡して編集する。バナー・図版・モック・写真加工など「画像そのものを作る/直す」ときに使用。文字を含む図版や納品物は --pro で Nano Banana Pro に切替
argument-hint: "<プロンプト> [--ref <画像>...] [--pro] [--aspect 16:9] [--size 2K] [-n N] [--outdir DIR | --out FILE]"
disable-model-invocation: false
allowed-tools: Bash(uv run --script ~/repos/github.com/elm-inc/agent-rules/skills/nano-banana/scripts/nano_banana.py*) Bash(uv run --script ~/.claude/skills/nano-banana/scripts/nano_banana.py*) Read
---

# Nano Banana 2 による画像生成・編集

Gemini の画像モデルで **テキスト→画像の生成** と **参照画像+指示→画像の編集** を行う。実体は `~/repos/github.com/elm-inc/agent-rules/skills/nano-banana/scripts/nano_banana.py` で、Claude は引数を組み立てて呼び、結果の画像を Read で確認してユーザーに報告する。

## 使用判断

| やりたいこと | 使うもの |
|---|---|
| 画像そのものを作る / 既存画像を直す | **このスキル** |
| UI・スライドの「AI っぽさ」を抜く | `/design-voice` (画像生成ではなく作風の矯正) |
| Figma からの画像書き出し | `/figma` (既存デザインの取得であって生成ではない) |

## モデル

| 指定 | モデル | 使いどころ |
|---|---|---|
| 既定 | `gemini-3.1-flash-image` (Nano Banana 2) | 通常の生成・編集。速く安い |
| `--pro` | `gemini-3-pro-image` (Nano Banana Pro) | **文字を含む図版**・納品物・高解像度 (`--size 2K/4K`) |

> **モデル ID は [`config/models.yml`](../../config/models.yml) が単一ソース**。ここやスクリプトを直に書き換えず、台帳を先に更新して `bash scripts/model-doctor.sh` を通すこと (根拠: [ADR-0017](../../docs/adr/0017-ai-workflow-model-refresh-and-review-layers.md))。

## 前提

- API キー: `GEMINI_API_KEY` → 無ければ `~/.gemini_token` (perms 600) の順に探す
- 無ければ https://aistudio.google.com/apikey で取得
- **`GEMINI_API_KEY= /nano-banana ...` (明示的に空) は fallback せず中止する** — 機密案件でクラウド送信を止める非常口。`/gemini-review` と同じ規約
- `uv` が必要 (スクリプトは PEP 723 + `uv run --script`)

## 引数の解釈

`$ARGUMENTS` の最初の非オプション文字列をプロンプトとして扱い、残りをそのままスクリプトに渡す。

| オプション | 意味 |
|---|---|
| `--ref <画像>` | 参照画像。**指定すると編集モード**になる。複数可 (合成・スタイル参照) |
| `--pro` | Nano Banana Pro を使う |
| `--aspect <比>` | `1:1` `2:3` `3:2` `3:4` `4:3` `4:5` `5:4` `9:16` `16:9` `21:9` |
| `--size <解像度>` | `1K` `2K` `4K`。**Pro 向け**。既定モデルでは無視されうる |
| `-n <N>` | 枚数。API を N 回呼ぶ (料金も N 倍) |
| `--outdir <DIR>` | 出力先ディレクトリ (既定 `./nano-banana`) |
| `--out <FILE>` | ファイル名を直接指定 (1 枚のときのみ) |
| `--json` | 結果を JSON で返す。Claude がパースするときはこちら |

## 実行手順

1. プロンプトが曖昧なら**先に具体化する**。画像生成は「何を・どんな構図で・どんな質感で」が薄いと平凡な結果に落ちる。ユーザーの意図が 1 行しかないときは、被写体 / 構図 / 光 / 質感 / 用途を補って提案し、合意してから実行する
2. `uv run --script ~/repos/github.com/elm-inc/agent-rules/skills/nano-banana/scripts/nano_banana.py <プロンプト> [オプション] --json` を実行 (**canonical な絶対パス**。相対パスだと他プロジェクトから呼んだとき cwd 依存で落ちる)
3. **生成された画像を Read で必ず確認する。** ファイルが出来たことと、意図どおりの絵が出たことは別物
4. 意図と違えば、プロンプトを直すか、**生成物を `--ref` に渡して差分指示で追い込む** (作り直すより編集の方が構図が安定する)
5. 保存先とモデル、追い込んだ場合はその経緯をユーザーに報告する

## 実測メモ (2026-08-28 / 本スキル作成時に確認)

- **生成**: `--aspect 1:1` → 1024x1024 JPEG。既定モデルで数秒
- **編集**: 「背景を濃紺グラデーションに、バナナはそのまま」で被写体を保持したまま背景のみ置換できた。**Nano Banana 系の主戦場はこちら**で、細かい指示によく従う
- **Pro**: `--size 2K --aspect 16:9` → 2752x1536。`NANO BANANA` の文字を破綻なく描画した。既定モデルは文字が崩れやすいので、**文字が要るなら最初から `--pro`**
- **アスペクト比はキャンバスの比**であって被写体の比ではない。「16:9 のポスター」と指示すると *16:9 の画面の中に置かれたポスター* が返ることがある。狙いが紙面そのものなら `--aspect 3:4` のように紙の比を指定する
- 出力形式はモデル任せで JPEG が返ることが多い。拡張子は返却 mime から決めている

## 注意

- 生成物は既定で `./nano-banana/` に落ちる。**リポジトリ内で実行するとコミット対象に入りうる**ので、成果物として残さないなら `--outdir` でスクラッチに逃がす
- `-n` は API を N 回呼ぶ。料金は枚数に比例する
- 人物・実在の商標・他者の著作物を含む生成は用途を確認してから行う
