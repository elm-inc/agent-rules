# AI 開発ワークフロー (多層・多モデル) 設計

- Linear Project: [AI 開発ワークフロー多層化](https://linear.app/elm-inc/project/ai-開発ワークフロー多層化-5d5bc734ffcd)
- ADR: [0017-ai-workflow-model-refresh-and-review-layers](../adr/0017-ai-workflow-model-refresh-and-review-layers.md) (2026-08-17 に [0001](../adr/0001-multi-llm-development-workflow.md) を Supersede) / [0019-frontier-tier-orchestration](../adr/0019-frontier-tier-orchestration.md) (2026-09-06)
- 制定日: 2026-05-22 / 最終棚卸し: **2026-09-06**
- 状態: **運用中。2026-09 に フロンティア層 (Fable 5.1 / GPT-6 Astra) を導入**

## 1. 背景・目的

AI に開発・レビュー・検証を任せる比率が上がるため、**単一モデル依存をやめて多層化** する。実装は Claude Opus 5 (高難度の要所は Fable 5)、レビュー・テスト生成を複数ベンダーの LLM (Anthropic / OpenAI / Google / DeepSeek / ローカル Qwen) で分担する。

Claude と GPT は学習分布が近く同じ間違い方をしやすいため、Gemini と DeepSeek を混ぜて思考の多様性を確保する。さらに pre-commit hooks 等の **機械検証 (非 AI)** を併用し、**3 層 (機械・LLM・人間)** で品質を担保する。

> **2026-08 の更新 (ADR-0017)**: モデル能力が圧縮され、差別化点がモデルからハーネス/検証へ移った。これを受けて役割の軸を「ベンダー → 固定割当」から「**その工程に何が要るか**」へ組み替え、レビューを **4 層 (床 / 多様性 / 深さ / 最後の砦)** に集約した。**多様性は自前スキル (異ベンダー 1 つ)、深さはハーネス標準 `/code-review`** と役割を分ける — ハーネスの多エージェント検証は全部 Claude なので groupthink を原理的に解けないため。

## 2. 採用したモデル・スキル

**モデル ID の単一ソースは [`config/models.yml`](../../config/models.yml)。下表は読み物で、正はそちら** (ADR-0017)。

| 層 | ロール | モデル / ツール | スキル | 採用理由 |
|---|---|---|---|---|
| — | 実装 (主) | Claude Opus 5 (要所は Fable 5.1) | (Claude Code 本体) | 長文推論・コード横断。Opus 4.8 と同価格で能力向上 |
| 床 (LLM) | 0 次レビュー | ローカル Qwen3-Coder-30B-A3B (vLLM/AWQ 4bit) | `/local-review` | コスト 0、機密データ送信不要、無制限。**199 tok/s**。機密案件は必須 / 公開リポは任意 (§4-1) |
| 床 | 探索・調査 | Claude Haiku 4.5 (+ 重い探索は Sonnet 5) | `explorer` / `researcher` | 司令塔の文脈とコストを節約 (ADR-0006) |
| 多様性 | セカンドオピニオン | Codex (既定 GPT-5.6 Sol) | `/codex-review` 他 | Anthropic と別ベンダー、修正提案が具体的。ID は Codex CLI 管理 |
| 多様性 (高リスク) | フロンティア級の異ベンダー | **GPT-6 Astra** | `/codex-review --astra` | 砦 (Fable 5.1) と同格の非 Anthropic。実費 $10/$50。ADR-0019 |
| 多様性 | 設計レッドチーム | DeepSeek V4-Pro (思考モード) | `/deepseek-redteam` | 別学習系統で深い問題発見、1 回 2 円前後 |
| 多様性 | リポ横断 | Gemini 3.1 Pro (入力 1M) | `/gemini-review` | cross-file 視点で唯一無二の指摘 |
| 深さ | 敵対的検証 | ハーネス標準 (Claude) | `/code-review` | 指摘を検証して絞る。**多様性は解けない** |
| 砦 | 最終レビュー | Claude Fable 5.1 | `/fable-review` | 高リスク変更のみ (ADR-0010 → 0019 のフロンティア枠規律) |
| — | テスト観点抽出 | DeepSeek V4-Flash + ローカル Qwen (+ 任意で Gemini) | `/test-generate --brainstorm` | 拡散的タスク、多モデルで観点カバレッジ向上 |
| — | テスト実装 / データ | ローカル Qwen | `/test-generate --implement` / `/test-data` | 収束的、単一モデルで十分。コスト 0 |
| — | テスト品質検証 | mutmut / Stryker | `/mutation-check` | AI 生成テストの tautology を機械検出 |
| 床 (機械) | 静的検証 | pre-commit hooks (ruff/mypy/semgrep) + `model-doctor` | (各リポで設定) | **常時必須**。LLM が構造的に見逃す種類 (リソースリーク等) を確実に取る。モデル退役も CI で検出 |

## 3. 運用フロー (実績ベース)

```
[設計]
  Claude が docs/design/foo.md 起草
   ├→ /deepseek-redteam で盲点炙り出し
   └→ (任意) /codex-audit で実装視点ツッコミ

[実装]
  Claude Opus 5 で実装 (高難度は Fable 5.1 委譲)

[コミット前]  ← 4 層。上から順に、必要な層だけ回す (ADR-0017)
  床      /local-review + pre-commit (型/lint/semgrep)   ← 常時。秒オーダー・0 円
          (必要時) /test-generate
  多様性  異ベンダーを 1 つだけ選ぶ:
            設計を疑う      → /deepseek-redteam
            10+ファイル/drift → /gemini-review
            実装視点         → /codex-review           (GPT-5.6 Sol)
            ★高リスク       → /codex-review --astra   (GPT-6 Astra・実費)
  深さ    /code-review                                   ← 敵対的検証で指摘を絞る
  砦      /fable-review                                  ← 高リスク変更のみ (Fable 5.1)

  ※ 高リスク変更では「多様性」を省略しない。深さ・砦はどちらも Claude 系なので、
     省くと異ベンダーの独立視点がゼロになる (ADR-0017 レッドチーム指摘)。
     さらに高リスク時は多様性層を Astra に【格上げ】する — 砦と同格の非 Anthropic を
     当てて初めて独立視点が砦と釣り合う (ADR-0019)。格上げであって追加ではないので、
     異ベンダーは依然 1 つまで

[実行検証]
  /verify, E2E テスト
```

軽微な変更では `/local-review` + pre-commit のみで十分。`/gemini-review` は 10+ ファイル変更や ADR drift 疑い時のみ。`/fable-review` はセキュリティ・課金・データ破壊・公開 API・並行処理などの高リスク変更のみ (条件表: `skills/fable-review/SKILL.md`)。**リポ横断は Astra に投げない** — 入力 272K 超で input 2x / output 1.5x になるため、1M context を使う横断は `/gemini-review` に残す。フロンティア層は「広さ」ではなく「深さ」に使う (ADR-0019)。

### 検証ループ recipe (verification / adversarial) — 2026-08 トレンド取り込み

レビューを「意見」で終わらせず、**経験的に検証して絞る**のが 2026 の定番 (最終品質 2-3x 改善の報告あり)。本リポの実践形:

1. **自己検証ループ**: 変更は「実行して確かめる」— build → test → observe (UI はスクショ)。AI が**合否を自走判定できる check** を与える (テスト・lint・`--dry-run`/`--diff`・E2E)。単発は `/verify`、多段は受け入れ基準を仕様に明記
2. **敵対的検証 (adversarial)**: 外部レビュアー (`/deepseek-redteam` で仮説生成・`/codex-review` で異種ベンダー・`/gemini-review` で横断) が指摘を出し、**Claude が経験的に調査して真偽を filter** する。所見は 集約→重複排除→重要度ランク付け してから対処 (盲目的採用しない)
3. **機械検証の床**: pre-commit (ruff/mypy/semgrep)・CI lint・`/mutation-check` を最前段フィルタに

要点: レビュー指摘を**そのまま採用せず、実行可能な check で裏取りしてから**反映する。出典: [Building verification loops (Anthropic)](https://claude.com/blog/building-verification-loops-in-claude-code-with-skills) (2026-08 参照)。

### spec-driven / 受け入れ基準 (Spec Kit の思想)

実装前に**仕様 + 各基準の pass/fail を確認する実行可能手段**を書く (drift 防止)。本リポは `docs/design/*.md` の受け入れ基準 + 検証手段欄で実践済み。フォーマットの参考に [GitHub Spec Kit](https://github.com/github/spec-kit) (2026-08 参照)。仕様が固まったら redteam → 実装 → 上記検証ループ、の順。

## 4. ベンチマーク実績

### 4-1. 2026-08 棚卸し時点 (ADR-0017)

ローカル LLM の載せ替え検証。RTX PRO 4500 Blackwell (32GB, sm_120) / vLLM 0.21.0 で**全候補を実際にロードして**測定:

| 候補 | 重み | 結果 | スループット |
|---|---|---|---|
| **cyankiwi/Qwen3-Coder-30B-A3B-AWQ-4bit** (MoE act 3B) | 16.9 GiB | ✅ 採用。KV cache 92,560 tok | **199 tok/s** |
| nvidia/Qwen3.6-35B-A3B-NVFP4 (MoE) | 21.8 GiB | ❌ OOM (MoE が非量子化に fallback) | — |
| nvidia/Qwen3.6-27B-NVFP4 (dense) | ~14 GiB | ❌ OOM (ModelOpt FP8 経路) | — |
| cyankiwi/Qwen3.6-27B-AWQ-INT4 (dense) | 19.0 GiB | ❌ OOM @32K ctx | — |
| (旧) RedHatAI/Qwen2.5-Coder-32B-FP8 | ~30 GiB | ⚠️ offload 6GB 必須 | 6 tok/s |

**結果: 速度 33 倍・context 22 倍 (4096 → 32768)**。ADR-0001 から積み残していた「Qwen 6 tok/s が律速」がここで解消した。

#### 検出品質: LLM と linter は補完関係にある (2026-08-17 実測)

「速度が 33 倍になったが品質は落ちていないか」を確認するため、**仕込みバグ 6 件**の Python に対して
新旧モデルを同一プロンプト・各 3 回で走らせ、さらに linter と突き合わせた。

| 仕込みバグ | 新 Qwen3-Coder-30B-A3B | 旧 Qwen2.5-Coder-32B | `ruff --select ALL` | mypy |
|---|---|---|---|---|
| mutable default argument | ✅ 3/3 | ✅ 3/3 | ✅ B006 | — |
| ファイル未 close | ❌ 0/3 | ❌ 0/3 | ✅ SIM115 | — |
| off-by-one (docstring と実装の食い違い) | ✅ 3/3 | ✅ 3/3 | ❌ | ❌ |
| lock 範囲が狭く race する | ✅ 3/3 | ✅ 3/3 | ❌ | ❌ |
| `is` で変数同士を比較 | ✅ 3/3 | ✅ 3/3 | ❌ | ❌ |
| 例外の握り潰し | ✅ 3/3 | ✅ 3/3 | ✅ BLE001 | — |
| **合計** | **5/6** | **5/6** | **3/6** | **0/6** |

読み取れること:

1. **新旧で検出力は同等 (5/6)**。載せ替えは速度 33 倍・context 8 倍を**品質を犠牲にせず**取れている。
   見逃しも両モデルで同一 (ファイル未 close)
2. **linter は意味的バグを 1 件も取れない**。`--select ALL` (全ルール) でも off-by-one・lock 範囲・
   変数同士の `is` はゼロ件で、出力は `D100` / `ANN001` 等のスタイル指摘に埋もれる。
   `F632` は**リテラルとの `is` にしか発火しない**ため変数同士は対象外
3. **逆に LLM は「ファイル未 close」を 6/6 で見逃した**。ruff は数ミリ秒で取る
4. **和集合で初めて 6/6**。床を「pre-commit + `/local-review`」の 2 本立てにしているのは正しく、
   **片方だけでは構造的に穴が残る**

新モデル固有の弱点も 1 つある: **指摘箇所は当てるが説明が雑になることがある**。
`is` 比較で旧モデルは「`==` を使うべき」と簡潔に正しく述べたのに対し、新モデルは
「文字列の場合に意図しない比較になる」と**場所は正しいが理由が的外れ**な説明をした
(実際は小整数キャッシュ外の int の問題)。出力量も約 2 倍冗長。
0 次レビューは後段で filter する前提なので許容範囲だが、**説明文をそのまま信じない**こと。

> **`/local-review` の起動条件** (この実測を踏まえた ADR-0017 の改訂):
> - **機密案件** (cloud 送信不可) では**唯一の LLM 選択肢なので必須**
> - **公開リポ**で異ベンダーを 1 つ回すなら**独立視点として重複するので省略可**
>
> レビュー層の真のコストは計算資源ではなく**読み手の注意**。0 円・オンデマンドでも、
> 冗長で説明が粗い指摘を読む時間は負債になる。

> **NVFP4 は理論上は最適だが現時点では使えない**。Blackwell ネイティブ 4bit だが vLLM 0.21.0 は sm_120 の NVFP4 **MoE カーネルを持たず bf16 に展開**する (vllm#31085)。vLLM 側の対応が入ったら再評価する。

その他の実測 (2026-08-17):

| 項目 | 実測 |
|---|---|
| DeepSeek V4-Pro 思考モード | `thinking:{type:enabled}` + `reasoning_effort` の**両方**必要。思考は `reasoning_content` に入る |
| Gemini 3.1 Pro | `thinkingBudget: 0` は **400 で拒否** (`only works in thinking mode`)。代替は `thinkingLevel: low\|medium\|high` |
| Gemini 3.1 Pro thinking 量 | 1 token の応答にも 46-176 thinking tok を消費。`maxOutputTokens` は潤沢に |

### 4-2. Phase 4 試運転 (2026-05・当時のモデル構成)

| スキル | LLM | 入力 tok | 出力 tok | 思考 tok | 応答時間 | 1 回コスト |
|---|---|---|---|---|---|---|
| `/local-review` | Qwen2.5-Coder-32B FP8 | 750 | 374 | — | 64.5s | $0 |
| `/deepseek-redteam` | DeepSeek-R1 | 691 | 2853 | 2621 chars | 42.3s | $0.007 |
| `/gemini-review` | Gemini 2.5 Pro | 1453 | 1196 | 3688 | 43.6s | $0.051 |
| `/test-generate` | Qwen | 425 | 1213 | — | 202s | $0 |
| `/test-data` | Qwen | 464 | 1312 | — | 219s | $0 |

### 検出品質
- `/local-review`: 仕込み 5 バグ全検出 ✅
- `/deepseek-redteam`: 12+ Critical/High 発見、HS256→RS256 等の代替案提案
- `/gemini-review`: **cross-file 固有の指摘** (型不整合・drift・dead code) — 他では検出不能
- `/test-generate`: 14 ケース + 境界値網羅、ただし AI assertion 要 review
- `/test-data`: 関係制約守る、Phase 5 でプロンプト改訂済

## 5. 振り返り

### 5-0. 2026-08 棚卸しで分かったこと (ADR-0017)

**一番の学びは「壊れていたことに気づけなかった」こと**。`deepseek-reasoner` (R1) は 2026-07-24 に退役していたが、モデル ID が
`skills/deepseek-redteam/SKILL.md` に直接埋まっていたため、**約 3 週間そのスキルは実行すれば必ず失敗する状態**だった。
ADR-0001 が想定していたのは「LLM の出力品質が落ちる」リスクで、「自分は何も変えていないのに上流が消える」という障害クラスは考慮外だった。

→ 対策として `config/models.yml` (台帳) + `scripts/model-doctor.sh` (drift 静的検査 + 上流実在確認) + CI を導入。

**副産物として、サプライチェーン guard `vllm-verify-model.sh` が一度も機能していなかったことも判明した**:

1. `while` をパイプの右辺に置いていたためサブシェルになり、`fail` の増加が親に伝わらず**改ざんを検出しても `exit 0`**
2. HF tree API の SHA256 は `.lfs.oid` にあるのに `.lfs.sha256` を読んでいたため、**全ファイルが skip**

「guard を置いた」ことと「guard が効いている」ことは別物で、**guard 自体にも検証が要る**。

**机上比較は当てにならない**。ローカルモデル選定では、ベンチマークとスペック上は NVIDIA の NVFP4 版が最適だったが、
実際にロードすると 2 種とも OOM した (vLLM が sm_120 の NVFP4 MoE カーネルを持たない)。
**候補は全部実際に起動して決める**のが結局は速い。

### 5-1. Phase 4-5 時点の振り返り

#### 何が効いたか
- **DeepSeek-R1 の高 ROI**: 7 円で設計の致命的問題を発見。`/codex-review` と組み合わせると groupthink を効果的に防ぐ
- **Gemini の cross-file 視点**: 単一ファイルでは見えない drift を確実に検出。コストは高いが「使い所」が明確
- **ローカル Qwen の常駐**: 0 次レビューを無限に回せる安心感。機密コードも送信不要
- **トークンファイル方式** (`~/.*_token` perms 600 + `env-snippet.sh`): バックアップ漏洩リスク低減

#### 何が効かなかったか・課題
- **Qwen 推論速度 6 tokens/sec が律速** — `/test-generate` `/test-data` で 200 秒超え
  - 原因: CPU offload 6GB の PCIe shuttle
  - Phase 6+ 対策: offload 3-4GB に削減、または 14B モデル切替検討
- **Gemini thinking コスト** — output tokens の 3 倍が thinking で消費
  - Phase 5 で `thinkingConfig.thinkingBudget: 0` オプション追加済
- **Qwen max_model_len 4096 制約** — KV cache 不足で縮小せざるを得なかった
  - Phase 6+ 対策: デスクトップ GPU 解放 + max_model_len 8192 に拡張

#### 落とし穴の記録
1. **HuggingFace unauthenticated レート制限** — 17GB で DL ストール。HF_TOKEN 必須
2. **online FP8 量子化で OOM** — 32B モデルは pre-quantized FP8 必須 (RedHatAI 等)
3. **Gemini 2.5 Pro は無料枠なし** — billing 必須 (Prepay or Standard)
4. **DeepSeek は前払い** — $2 入金必要
5. **Gemini thinking デフォルト有効** — maxOutputTokens 不足で出力 0
6. **Qwen context 制約と max_tokens のハードコード** — `VLLMValidationError` 注意

## 6. コスト見通し

### ローカル LLM
- GPU 稼働 24h 想定 (idle 30W、推論時 200W)
- 月電気代: 約 1000-3000 円 (日本平均単価)
- API コスト: 0

### クラウド LLM (1 開発者あたり 1 ヶ月想定)
| API | 月の想定使用 | 月額 |
|---|---|---|
| Claude (Anthropic) | 既存 (Opus 5 / Fable 5) | (既存 + Fable 超過分。ADR-0010) |
| Codex (OpenAI) | 既存 | (既存) |
| Gemini 3.1 Pro | `/gemini-review` × 10-20 回 | $2-5 |
| DeepSeek V4-Pro/Flash | `/deepseek-redteam` × 30-50 回 | $0.5-1 |

**サイドベンダーの追加コストは月 $3-6 程度で、金額としては誤差**。コスト管理の焦点は一貫して **Anthropic のティア選択 (Opus 5 か Fable 5 か)** にある — 2026-06 の Fable 実測は約 3 日で ~$595 で、サイドベンダー年間分を数日で超える。ADR-0010 の規律が効くのはこちら。

## 7. 次の改善案 (Phase 5 引継ぎ + 今後)

### 短期 (Phase 5 で対応済)
- [x] Gemini maxOutputTokens 8192 デフォルト化
- [x] `/test-data` プロンプト改訂 (件数指定、地域多様性、過剰解釈防止)
- [x] `/test-generate` 動的 max_tokens + 実行検証フロー
- [x] `/local-review` 動的 max_tokens + 大差分分割勧告

### 完了 (2026-08 棚卸し / ADR-0017)
- [x] **Qwen の速度律速を解消** — CPU offload 撤廃 + MoE 化で 6 → 199 tok/s、max_model_len 4096 → 32768
- [x] **モデル退役の自動検知** — `config/models.yml` + `scripts/model-doctor.sh` + CI (`model-drift.yml`)
- [x] **レビュー層の責務重複を整理** — ADR-0001 の宿題。6 スキル → 4 層に再定義
- [x] サプライチェーン guard の実バグ 2 件修正 (詳細は §5-0)

### 中期 (Phase 6+)
- [ ] デスクトップ GPU プロセス停止 (Xorg・gnome-shell が 2.2 GiB 常時占有。空ければ更に余裕が出る)
- [ ] NVFP4 の再評価 (vLLM が sm_120 の NVFP4 MoE カーネルに対応したら)
- [ ] `/multi-review` (複数 LLM 並列実行 + マージ)
- [ ] `/local-review` の pre-commit hook 自動化
- [ ] 試運転の CI 自動化 (回帰検出)

### 長期
- [ ] 組織コンプライアンス確認 (DeepSeek 中国経由の許容範囲)

## 8. 実運用データ追記欄

> **このセクションは月次で更新する。** 1-2 ヶ月運用後の実データに基づき、上記の見積を補正・ROI を確定する。

### 月別使用頻度

| 月 | `/local-review` | `/codex-review` | `/deepseek-redteam` | `/gemini-review` | `/test-generate` | `/test-generate --brainstorm` ★ | `/test-data` |
|---|---|---|---|---|---|---|---|
| 2026-05 (本月、暫定) | — | — | — | — | — | 1 (Phase 8 試運転) | — |
| 2026-06 | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

★ ADR-0002 採択 (2026-05-24) で追加された新モード。詳細: [phase8-brainstorm-trial.md](../setup/notes/phase8-brainstorm-trial.md)

### 月別コスト集計

`scripts/track-cost.sh` で集計 (Phase 6 雛形)。**フロンティア層 (Fable 5.1 + GPT-6 Astra) は `scripts/frontier-usage.sh` が自動集計**し、statusline に `🧠FR` として常時表示する。予算 **$100/月は 2 モデル共有** (`FRONTIER_BUDGET_USD`)。根拠: ADR-0010 → [ADR-0019](../adr/0019-frontier-tier-orchestration.md)。

> ⚠️ **2 つのフロンティアは課金も計測も非対称。同じ数字として読まない** (ADR-0019 §5):
>
> | | included | ローカル計測 | 表示の意味 |
> |---|---|---|---|
> | **Fable 5.1** | Max は週次上限の 50% まで (恒久)、超過分のみ実費 | transcript の `usage` を実測 | included 未考慮の**上限見積り** (実費 ≤ 表示値) |
> | **GPT-6 Astra** | **無し (全量実費)** | Codex が別プロセスのため transcript に残らない。usage API は admin scope 必須で通常キーは 403 | `codex-astra.sh` の**呼び出し台帳**。トークン不明の回は未計上 = **下限** (statusline の `+`) |
>
> 実費の正は Console ([Anthropic](https://console.anthropic.com/settings/usage) / [OpenAI](https://platform.openai.com/usage))。

| 月 | Fable | Astra | Gemini | DeepSeek | 合計 |
|---|---|---|---|---|---|
| 2026-05 | — | — | TBD | TBD | TBD |
| 2026-06 | ~$595 ⚠️ | — | TBD | TBD | TBD |
| 2026-07 | TBD (7/1-19 included / **7/20〜 従量課金**) | — | TBD | TBD | TBD |
| 2026-09 | 導入初月 (計測中) | 導入初月 (計測中) | TBD | TBD | TBD |

> **⚠️ 2026-06 の Fable ~$595 は約 3 日 (6/10〜6/13、6/12 の利用停止まで) の複数プロジェクト横断利用による実測** (`frontier-usage.sh --month 2026-06`)。予算 $100/月なら 1 日で超過する規模で、厳選 + モニタリング (ADR-0010) の必要性を裏付ける実データ。7/20 以降は included (週次上限の 50%) を超えた分が実費として請求される。

### ROI 判定

**主観評価をやめ、仕込みバグに対する検出率で測る**方針に変更した (ADR-0017)。
「防いだバグ数」は反実仮想なので数えられず、3 ヶ月間 `TBD` のまま埋まらなかった。

#### 測定済み (2026-08-17)

| 層 | 検出率 | 一意の貢献 | 判定 |
|---|---|---|---|
| 床 (機械) `pre-commit` | 3/6 | **リソースリーク** (LLM は 6/6 見逃し) | **必須**。代替不能 |
| 床 (LLM) `/local-review` | 5/6 | off-by-one・lock 範囲・変数同士の `is` (linter は全ルールでも 0/3) | **機密案件は必須**。公開リポは異ベンダーと重複 |
| 多様性 `/deepseek-redteam` | — | 設計の抜け穴 (本 ADR 自体に Critical 3 件) | **維持**。設計フェーズで最も効く |
| 多様性 `/codex-review` | — | CI/配線の具体的欠陥 (P2 2 件、DeepSeek と重複ゼロ) | **維持**。実装フェーズで効く |
| 深さ `/code-review` | — | 敵対的検証 (全部 Claude なので多様性は解けない) | 維持 |
| 砦 `/fable-review` | — | 未計測 | 高リスク限定を維持 (ADR-0010) |

測定手順は再現可能にしてある: 仕込みバグ入りの対象を用意し、同一プロンプトで各層を 3 回走らせ、
検出率と誤検知を数える。層を追加・削除するときは同じ手順で測る。

#### 未測定 (次にやるべき最重要)

- **`/local-review` は Opus 5 (実装者自身) が見逃すものを拾えるか**。
  これが床 (LLM) の本当の ROI だが未検証。参考値として ADR-0017 の作業中 (n=1) は、
  実際に欠陥を見つけたのは Opus 5 自身の読み・DeepSeek・Codex で、`/local-review` は 0 件だった
- 多様性層とハーネス層 (`/code-review`) の指摘がどれだけ重複するか

## 9. 関連リンク

- ADR: [0001-multi-llm-development-workflow.md](../adr/0001-multi-llm-development-workflow.md)
- Phase 別実行記録:
  - [Phase 2: vLLM セットアップ](../setup/notes/phase2-trial.md)
  - [Phase 3: クラウド API セットアップ](../setup/notes/phase3-trial.md)
  - [Phase 4: 試運転と検証](../setup/notes/phase4-trial.md)
  - [Phase 5: フィードバック反映](../setup/notes/phase5-feedback.md)
- Linear Project: https://linear.app/elm-inc/project/ai-開発ワークフロー多層化-5d5bc734ffcd
- GitHub Branch: `feat/linear-skills`
