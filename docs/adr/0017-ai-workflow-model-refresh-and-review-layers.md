# ADR-0017: AI 開発ワークフローの棚卸し — モデル刷新・レビュー 4 層集約・モデル台帳

## ステータス

採択 (2026-08-17)

[ADR-0001](0001-multi-llm-development-workflow.md) を **Supersede** する。役割分担の考え方 (多層・異ベンダー・機械検証の 3 層) は引き継ぎ、モデル選定と層の切り方を作り直す。
[ADR-0006](0006-orchestration-methods.md) の方式 (spec 駆動 / 役割特化サブエージェント / ファンアウト規律) は**そのまま有効**。

## 文脈

ADR-0001 の制定 (2026-05-22) から 3 ヶ月で、前提が 4 種類の形で崩れた。

### 1. 黙って壊れていた

`deepseek-reasoner` (R1) は **2026-07-24 に退役**していた。`GET api.deepseek.com/v1/models` の現存モデルは `deepseek-v4-flash` / `deepseek-v4-pro` の 2 つのみ。
`/deepseek-redteam` と `/test-generate --brainstorm` は**約 3 週間、実行すれば失敗する状態**だったが、誰も気づかなかった。モデル ID がスキル本文に直接埋まっており、退役を検知する仕組みが無かったためである。

これは ADR-0001 が想定していなかった障害クラス — 「自分の設定は変えていないのに、上流が消えたので壊れる」。

### 2. 期限付きで陳腐化していた

- `gemini-2.5-pro` は **2026-10-16 退役予定**。後継は `gemini-3.1-pro-preview` (入力 1,048,576 tok / 出力 65,536 tok)
- 移行に伴い **`thinkingConfig.thinkingBudget: 0` が使えなくなる** (`400 Budget 0 is invalid. This model only works in thinking mode.`)。`/gemini-review` のコスト削減手順がそのままでは 400 になる。代替は `thinkingLevel: low|medium|high`

### 3. モデル勢力図が動いた

| 変化 | 影響 |
|---|---|
| **Opus 5** が Opus 4.8 と同価格 ($5/$25) で登場 | セッションモデルが更新され、CLAUDE.md の「Opus 4.8」表記がズレた。Fable 5 ($10/$50) との相対価値が下がり、[ADR-0010](0010-fable-metered-billing-controls.md) の厳選方針はむしろ強化される |
| **Sonnet 5** が near-Opus @ $3/$15 | 並列サブエージェントの主力候補が増えた |
| **Codex 既定が GPT-5.6 Sol** (2026-07-09〜) | セカンドオピニオンの質が上がった。ID 固定は不要 |
| **Qwen3.6 世代** (2026-04) が 32GB 級に降りてきた | ADR-0001 の積み残し「Qwen 6 tok/s が律速」を解消できる |

### 4. ADR-0001 自身の宿題が未着手

ADR-0001 は「スキル間の責務重複 → 1-2 ヶ月運用後に整理」と宣言していたが 3 ヶ月未着手。`docs/design/ai-workflow.md` §8 の実運用データも `TBD` のまま。
この間に Claude Code 本体が `/code-review` (敵対的検証つき) や Workflow ファンアウトを標準搭載し、**自前の多層レビューと役割が重なった**。

### 業界側の収束

2026 時点で、フロンティアモデルはコーディングで軒並み SWE-bench 85-90% 帯に収束し、差別化点は**モデルからハーネス/検証ループへ移った**。read → plan → build → **verify** → ship が標準形。

## 決定

### 1. レビューを 4 層に再定義する

役割の軸を「ベンダー → 固定割当」から「**その工程に何が要るか**」へ組み替える。

| 層 | 何のために置くか | 担当 | 起動条件 |
|---|---|---|---|
| **床** | 無限に回す・機密 OK・0 円 | ローカル LLM (`/local-review`) + pre-commit | 常時 |
| **多様性** | groupthink 回避 | **異ベンダーを 1 つだけ**選ぶ<br>設計 → `/deepseek-redteam` / 横断 → `/gemini-review` / 実装視点 → `/codex-review` | 差分の性質で選択 |
| **深さ** | 指摘を敵対的に検証して絞る | ハーネス標準 `/code-review` (+ 巨大タスクは Workflow ファンアウト) | 品質を上げたいとき |
| **最後の砦** | 下流への波及が大きい変更 | `/fable-review` (Fable 5) | 高リスク変更のみ |

**核心**: ハーネス標準の多エージェント検証 (`/code-review ultra` 等) は**全エージェントが Claude なので groupthink を原理的に解けない**。逆に自前の多層スキルは敵対的検証ループを持たない。両者は競合ではなく相補であり、**「多様性は自前スキル、深さはハーネス」**と役割を分ける。

**常時 2 つ以上の異ベンダーを回さない**。ADR-0001 は DeepSeek と Gemini を別々の役割として常設したが、モデル能力が圧縮された今、2 つ回すコストに見合う追加検出はない。差分の性質で 1 つ選ぶ。

### 2. モデル ID を台帳に集約し、機械検証する

再発防止の本体。

- **`config/models.yml`** — 全スキル/スクリプトが使うモデル ID の単一ソース。`active` と `retired` を持つ
- **`scripts/model-doctor.sh`**
  - `--drift`: operational surface (`CLAUDE.md` / `skills/` / `scripts/` / `agents/` 等) に現れるモデル ID が台帳の `active` に登録済みか、退役 ID が残っていないかを静的検査する。**API キー不要**なので CI で回せる
  - `--probe`: `active` の各 ID がベンダー API に実在するか実際に問い合わせる。退役予定日が 90 日以内のものを警告
- **`.github/workflows/model-drift.yml`** — PR で `--drift` を強制

`docs/adr/` と `docs/design/` は走査対象外とする。過去の判断として旧モデル名を書くのは正しいため。

### 3. ローカル LLM を Qwen3-Coder-30B-A3B (AWQ 4bit) に載せ替える

`RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic` (dense 32B・重み約 30 GiB) は 32GB カードに収まらず `--cpu-offload-gb 6` を強いられ、**6 tokens/sec・`max_model_len 4096`** が律速だった。

→ **`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`** (MoE total 30B / active 3B / apache-2.0) に変更する。

**候補は机上比較で決めず、本機 (RTX PRO 4500 Blackwell 32GB, sm_120 / vLLM 0.21.0) で全部ロードして決めた**:

| 候補 | 重み | 結果 |
|---|---|---|
| **cyankiwi/Qwen3-Coder-30B-A3B-AWQ-4bit** (MoE) | 16.9 GiB | ✅ **採用**。KV cache 92,560 tok / **199 tok/s** |
| nvidia/Qwen3.6-35B-A3B-NVFP4 (MoE) | 21.8 GiB | ❌ OOM。MoE 層が `Unquantized MoE backend` に落ち bf16 で展開 |
| nvidia/Qwen3.6-27B-NVFP4 (dense) | ~14 GiB | ❌ OOM。`ModelOptFp8LinearMethod` が FP8 として ~27 GiB 確保 |
| cyankiwi/Qwen3.6-27B-AWQ-INT4 (dense 27B) | 19.0 GiB | ❌ OOM @32K ctx (4bit 自体は効いた) |
| Qwen/Qwen3.6-27B-FP8 (公式 dense) | 28.7 GiB | ✗ デスクトップが常時 2.2 GiB 使うため KV cache が残らない |
| zai-org/GLM-5.2-FP8 | 703.7 GiB | ✗ 単機に載らない |

**結果: 速度 33 倍 (6 → 199 tok/s)・context 22 倍 (4096 → 32768)**、CPU offload 撤廃。

> **NVFP4 は現時点では使えない**、が最大の学び。Blackwell ネイティブの 4bit 形式で理論上は最適だが、vLLM 0.21.0 は sm_120 で NVFP4 の **MoE カーネルを持たず bf16 に展開する** (vllm#31085)。dense 版も ModelOpt の混在チェックポイント処理で FP8 相当を確保して落ちる。**将来 vLLM 側が対応したら再評価する**価値がある。

### 4. サプライチェーン検証を「org 許可 + commit pin」の 2 経路にする

採用した AWQ 版の発行元 `cyankiwi` は個人アカウントで、`scripts/vllm-verify-model.sh` の許可 org (`Qwen|deepseek-ai|RedHatAI|mistralai|google|meta-llama`) に入らない。
しかし決定 3 のとおり、**公式 org 経路は実測で全滅した** — Qwen 公式は 4bit 版を出さず (bf16 60GB / FP8 34.9 GiB のみ)、RedHatAI に build は無く、NVIDIA の NVFP4 は 2 種とも動かない。

→ 信頼経路を 2 つにする:

- **(A) 許可 org** — 従来どおり。`nvidia` を追加する (NVFP4 は今回不採用だが、Blackwell 向け公式配布元として今後の再評価に備える)
- **(B) 台帳 commit pin** — `config/models.yml` に **commit SHA 付き**で登録されているものは、org 単位ではなく「その 1 コミットだけ」を信頼する。`--revision` で vLLM にも同じ SHA を渡し、リポジトリが後から書き換わっても取り込まない

**併せて `vllm-verify-model.sh` の実バグを 2 件修正する。この guard は今まで一度も機能していなかった**:

1. `while` をパイプの右辺に置いていたためサブシェルになり、`fail` の増加が親に伝わらず**改ざんを検出しても `exit 0`** していた
2. HF tree API の SHA256 は `.lfs.oid` にあるのに `.lfs.sha256` を読んでいたため、**全ファイルが "no LFS SHA" で skip** されていた

修正後は実際に 4 ファイルの SHA256 照合が走ることを確認済み。

### 5. `/test-generate --with-distill` を廃止する

`deepseek-ai/DeepSeek-R1-Distill-Qwen-14B` は**退役した R1 の蒸留**であり、同じ役割は API の `deepseek-v4-flash` が桁違いに安く高品質にこなす。
さらに実装が GPU swap (docker stop → 別コンテナ起動 → 復帰) を伴い、OOM と復帰失敗のリスクを抱えていた。決定 1 の「多様性ソースは 1 つ」にも反する。

## 根拠

- **退役検知の機械化が最大の価値**。今回の実害はモデルが古かったことではなく、**壊れているのに気づけなかったこと**。台帳 + CI は「次に上流が消えたとき、PR で落ちる」を保証する
- **層を減らすほど各層が実行される**。6 つのレビュースキルは「どれを使うか」の判断コストが高く、結果として `/local-review` だけが回る状態になりやすい。4 層 + 選択規則の方が実効カバレッジが上がる
- **多様性は自前でしか買えない**。ハーネスがどれだけ多エージェント化しても全部 Claude である以上、異ベンダーを 1 つ保つ価値は残る。逆に敵対的検証はハーネスに任せた方が良い (自前実装より作り込まれている)

## レッドチーム指摘への対応 (`/deepseek-redteam`, 2026-08-17)

本 ADR 自体を、修復した `/deepseek-redteam` (DeepSeek V4-Pro) にかけた結果と対応:

| 指摘 | 判定 | 対応 |
|---|---|---|
| **CI は元の事故 (上流が黙って消える) を検知できない**。`--drift` は台帳との突合のみで、台帳に active として残っていれば green | ✅ 妥当・最重要 | `--probe` を **`/status` に組み込み** (7 日経過で自動実行、失敗は注意欄の先頭)。CI にも週次 schedule job を追加。**キーが実在するローカルが主経路、CI は保険** |
| **0 件検出が fail-open**。パターン陳腐化で何も検出しなくても green | ✅ 妥当 | 0 件を `fail` に変更 (検査が壊れたと解釈する) |
| **許可 org に `nvidia` を足したのに検査パターンに `nvidia/` が無い** | ✅ 妥当 | パターンの HF org 一覧を許可 org の上位集合にし、コメントで不変条件を明記 |
| 走査対象に `.github/` が無い | ✅ 妥当 | 追加。追加した直後に自分の workflow が引っかかった |
| `--probe` が全 skip でも exit 0 | ✅ 妥当 | 1 つも確認できなければ `fail` |
| 退役予定の基準日がハードコード | ✅ 妥当 | 実行日を使う |
| **4 層集約で高リスク変更の独立検証が失われる**。最後の砦 `/fable-review` も Claude 系 | ✅ 妥当 | 決定 1 を修正 — **高リスク変更では「多様性」層を必須**にした (下記) |
| `model-doctor:allow` は一行で検査を無効化できる | ⚠️ 設計どおり | 明示マーカーは意図的。抑止はコードレビューで行う。**暗黙に許すより、意識してマークさせる方が良い**という判断 |
| commit pin は models.yml への PR で骨抜きにできる | ⚠️ 想定脅威外 | 本 guard の脅威モデルは「上流が消える/書き換わる」であって悪意ある内部 PR ではない。後者は通常のレビューで防ぐ |
| 動的結合 (`deepseek-${SUFFIX}`) は grep で検出できない | ⚠️ 既知の限界 | 検出できないことを受け入れる。**モデル ID を動的に組み立てない**運用で回避する |

**決定 1 の修正**: 高リスク変更 (セキュリティ・課金・データ破壊・公開 API・並行処理) では、
**「多様性」層を省略しない**。`/fable-review` は Claude 系であり、`/code-review` も Claude 系なので、
砦だけでは異ベンダーの独立視点がゼロになる。高リスク時は 床 → 多様性 → 深さ → 砦 を全て通す。

## トレードオフ / 不採用

- **不採用: 6 層維持 + 使い分け条件の厳密化** — ROI データが無い状態で条件表だけ増やしても判断コストが上がるだけ。層を減らして実行率を上げる方を採る
- **不採用: 新世代 dense (`Qwen3.6-27B`, 77.2% SWE-bench)** — ベンチマークは採用モデルより上だが、AWQ 4bit でも 32K context で OOM し、かつ dense = 全パラメータ active で「無限に回す床」には速度が合わない。**この層で効くのは品質よりスループット**
- **不採用: `zai-org/GLM-5.2`** — open-weight 最強クラス (SWE-bench Pro 62.1%) だが FP8 で 703.7 GiB。データセンター級で単機に載らない
- **引き受けるリスク: 個人アカウント発行の量子化物に依存する** — 公式 org 経路が実測で全滅したうえでの選択。commit pin + SHA 照合で「この 1 コミット」に限定して緩和するが、**発行者がリポジトリを消した場合は再取得できない**。ローカルキャッシュを消す前に別候補を確保すること
- **引き受けるリスク: 採用モデルは 2025-07 世代** — Qwen3.6 (2026-04) より 9 ヶ月古い。0 次レビュー用途では速度を優先したが、より新しい MoE の 4bit 版が出たら再評価する
- **引き受けるリスク: `-preview` サフィックス** — `gemini-3.1-pro-preview` は GA 化で ID が変わりうる。`model-doctor.sh --probe` の定期実行で検知する

## 影響範囲

- 追加: `config/models.yml`, `scripts/model-doctor.sh`, `.github/workflows/model-drift.yml`, 本 ADR
- 変更: `CLAUDE.md` (役割表・4 層), `docs/design/ai-workflow.md`
- 変更 (スキル): `deepseek-redteam`, `gemini-review`, `test-generate`, `local-review`, `fable-task`, `fable-review`
- 変更 (スクリプト): `ensure-vllm.sh`, `start-vllm.sh`, `vllm-verify-model.sh`, `vllm-swap-to.sh`, `migrate-hf-cache.sh`, `env-snippet.sh`, `test-deepseek.sh`, `test-gemini.sh`
- 変更: `templates/systemd/vllm-qwen-coder.service`
- 削除: `/test-generate --with-distill`

## 関連

- [ADR-0001](0001-multi-llm-development-workflow.md) — Superseded by this ADR
- [ADR-0002](0002-multi-model-test-generation.md) — `--brainstorm` の参加モデルを更新 (方式は維持)
- [ADR-0005](0005-on-demand-local-llm.md) — オンデマンド起動は維持
- [ADR-0006](0006-orchestration-methods.md) — 方式は維持
- [ADR-0010](0010-fable-metered-billing-controls.md) — Opus 5 登場で Fable の相対価値が低下、規律は強化
- [docs/design/ai-workflow.md](../design/ai-workflow.md)

## 改訂履歴

- 2026-08-17 採択
