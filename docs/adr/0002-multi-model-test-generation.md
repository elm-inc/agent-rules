# ADR-0002: テスト工程の多モデル化 + ローカル量子化モデル併用

## ステータス

提案 (2026-05-24)

## 文脈

ADR-0001 で **レビュー** を多層・多モデル化し、Phase 4-5 で実績が出た:

- DeepSeek-R1 が 7 円で設計の致命的問題を発見 (groupthink 回避)
- Gemini 2.5 Pro が cross-file の drift を独占検出
- ローカル Qwen が 0 次レビューを無料・無制限で回せる

一方、**テスト工程** は現状 `/test-generate` (Qwen 主 + DeepSeek-R1 property 発想) と `/test-data` (Qwen バッチ) の 2 スキルのみで、レビューほど多モデル化が進んでいない。AI 比率の上昇に伴い、テストの**観点抽出** (どんな失敗を想定するか) も groupthink リスクを抱える。

加えて、現状クラウド API モデル (DeepSeek-R1 / Gemini / Codex) は月 $2-3 程度の小コストで運用中だが、以下の余地がある:

- **DeepSeek-R1-Distill 系** は思考連鎖能力を保ったまま 7B/14B サイズで配布されており、RTX PRO 4500 Blackwell (32GB GDDR7, FP4/FP8 ネイティブ) に Qwen と**同時ロード可能**
- **AWQ INT4** で Qwen-Coder-14B を約 5GB に圧縮できれば、複数モデル常駐が現実的になる
- Qwen-Coder-32B FP8 (現状) は 23GB を専有し、KV cache を圧迫 (`max-model-len 4096` に制限)。AI 比率上昇下では同時併用の柔軟性が品質を左右する

これらに対応するため、**テスト工程の多モデル化** と **ローカル量子化モデルの併用基盤** を本 ADR で決定する。

## 決定

### 1. テスト工程をフェーズ別に役割分担する

| フェーズ | 担当モデル | 多モデル化方針 |
|---|---|---|
| ① 観点・境界条件の抽出 | DeepSeek-R1 + Gemini + Qwen を並列 | **多モデル化** (groupthink 防止が最大のリターン) |
| ② テストケース列挙 | Qwen-Coder (ローカル) | 単一で十分、必要に応じ Codex で代替案 |
| ③ テスト実装 (コード生成) | Qwen-Coder または Claude Opus 4.7 | 単一、品質は pre-commit + 人間で担保 |
| ④ テストデータ生成 | Qwen-Coder (主) + Gemini (schema 横断時のみ) | 限定的多モデル化 |

**根拠**: 観点抽出は「忘れがちな失敗ケースを発想する」拡散的タスクで、モデル多様性がそのままカバレッジに直結する。実装は収束的タスクで重複ばかり増えるため単一モデルで十分。

### 2. `/test-generate` を 2 モードに分割する

- `/test-generate <target> --brainstorm`: 観点抽出フェーズ。DeepSeek-R1 + Gemini + Qwen を並列実行し、観点リストをマージして提示
- `/test-generate <target> --implement <観点ファイル>`: 観点リストを入力にコード生成 (Qwen 単一)
- 引数なし `/test-generate <target>`: 後方互換、現状と同じ単一フロー (Qwen 主)

### 3. ローカル量子化モデルを 2 段構成で運用する

| モデル | 量子化 | VRAM | 用途 |
|---|---|---|---|
| Qwen2.5-Coder-32B | FP8 | 〜23GB | 実装・コード生成 (現状維持) |
| Qwen2.5-Coder-14B | AWQ INT4 | 〜5GB | 高速ループ・観点抽出時の補助 |
| DeepSeek-R1-Distill-Qwen-14B | AWQ INT4 | 〜5GB | レッドチーム・観点抽出 (API DeepSeek-R1 の代替候補) |

**運用方式**:
- 32B FP8 は常駐 (現状通り)
- 14B 系 2 種は **動的ロード** (vLLM `--swap-space` または別ポートでサブ vLLM 起動)
- 同時ロード可否はベンチマークで判定 (32 + 5 + 5 = 33GB は overhead 込みで microscopic に厳しい)

### 4. API モデル課金枠は維持・拡張する

DeepSeek-R1-Distill のローカル化はあくまで**選択肢追加**であり、**API 版を置き換える前提ではない**:

- オリジナル DeepSeek-R1 (API) と distill ローカル版の品質差を A/B 評価
- distill で品質が落ちる領域 (例: アーキテクチャ全体俯瞰) は API 版を継続
- 月 $2-3 程度のクラウド枠は維持、効果的なら拡張も可

### 5. 機密性ポリシーは ADR-0001 を継承する

- ローカル LLM (Qwen + distill) は無制限
- クラウドは公開 OSS および差分レベルに留める
- distill のローカル化により、機密度の高いコードの観点抽出も local だけで完結可能に

## 理由

### Why テスト観点抽出だけ多モデル化

- **拡散的タスクは多モデルでカバレッジが伸びる**: 観点抽出は「思いつく失敗ケース」の集合演算であり、訓練分布が異なるモデルを併用することで union が広がる
- **収束的タスクは単一で十分**: テスト実装コード生成は正解が比較的明確で、複数モデルを動かしても重複出力ばかりで ROI が下がる
- **コスト的にも合理的**: 観点抽出は 1 タスク数千トークン、実装は数万トークン。多モデル化は前者に限定すればコスト増は最小

### Why ローカル distill 化の追加

- **API コスト削減目的ではない** (現状月 $1 程度で十分小さい)
- **目的はレート制限フリー + 機密データ送信ゼロ + 並列化**: distill ローカル化により、機密案件でも観点抽出に思考連鎖モデルを使える
- **GPU 投資の活用**: 32GB GDDR7 + FP8 ネイティブを 23GB 1 モデル専有では遊ばせている

### Why AWQ INT4 採用

- FP8 (現状) でも 14B は 8GB、AWQ INT4 なら 〜5GB に圧縮
- vLLM は AWQ をネイティブサポート、Blackwell の FP4 テンソルコアも順次サポート進行中
- 品質劣化は INT4 でも 2-3% 程度で実用範囲 (Qwen 公式評価より)

## 検討した代替案

### 代替案 A: テスト工程は現状維持

- Pros: 運用シンプル、追加コストなし
- Cons: 観点の偏り (Qwen 単独依存) を放置、AI 比率上昇下で品質単一障害点が残る
- 不採用理由: ADR-0001 の問題意識 (groupthink 回避) と整合しない

### 代替案 B: 全フェーズ多モデル化 (実装も観点も)

- Pros: 最高カバレッジ
- Cons: コスト 3-5 倍、運用複雑性大、収束的タスクでは重複ばかり
- 不採用理由: ROI が悪い。実装は単一で十分という Phase 4-5 知見と矛盾

### 代替案 C: DeepSeek-R1-Distill-Qwen-32B を採用 (14B でなく)

- Pros: 元の R1 にもっと近い品質
- Cons: VRAM 〜25GB で Qwen-Coder-32B との同時ロード不可、swap 必須
- 不採用理由: 同時ロードによる即応性を優先 (14B でも実用品質との Anthropic blog 評価あり)

### 代替案 D: クラウド API のみ拡張、ローカルは追加しない

- Pros: ハードウェア依存なし、セットアップ簡単
- Cons: 機密データ送信制限、レート制限の影響
- 不採用理由: ADR-0001 のローカル LLM 採用理由と整合しない

### 代替案 E: 32B も AWQ INT4 化し、3 モデル同時ロードを物理的に成立させる

- Pros: 32B INT4 (~16GB) + 14B INT4 × 2 (~14GB) = ~30GB で 32GB VRAM に確実に収まる。同時ロード前提の運用が破綻しない
- Cons: 32B FP8 → INT4 でコード生成品質が劣化する可能性 (Qwen 公式評価で 2-3% 程度だが、コード生成 domain での実測は未確認)
- 不採用理由: Phase 1 ベンチマークで FP8/INT4 の品質差を実測してから判断。INT4 で品質が許容範囲なら本案へ切替も視野
- 採用条件: Phase 1 ベンチマークで「Qwen-Coder-32B INT4 のバグ検出率が FP8 比 -5% 以内」を満たすこと

## 帰結

### Pros

- テスト観点のカバレッジ向上 (groupthink 防止)
- 機密案件でもレッドチーム可能 (distill ローカル化)
- GPU 投資の活用度向上 (複数モデル併用)
- API モデルとの併用で、クラウド側の優位 (最新性) と local 側の優位 (常時性) を両立

### Cons

- vLLM 構成の複雑化 (複数モデル同時 or swap 管理)
- distill 版のセットアップ・ベンチマークコスト (Phase 別実施)
- スキル仕様変更 (`/test-generate` 2 モード化) で既存ユーザーへの周知が必要
- 同時ロード時の電力消費増 (推定 +50-100W、月 500-1500 円程度)

### 引き受けるリスク

- **distill 版の品質劣化リスク** → A/B ベンチマークで判定、品質不足なら API 版継続
- **VRAM 不足リスク (Critical)**: 当初の同時ロード見積 (32B FP8 + 14B AWQ × 2 = 33GB) は KV cache と vLLM overhead を含めると実 36-42GB 必要で 32GB に収まらない。**Phase 1 で実測必須**、不可なら代替案 E (全 INT4 化) または swap 方式に切替
- **同時アクセス OOM**: `/test-generate --brainstorm` を複数 worktree セッションから同時呼出すと VRAM 専有が衝突して即 OOM。**wrapper 側でセマフォ排他必須**
- **`/test-generate` 仕様変更で混乱** → 引数なしの旧挙動は後方互換維持、新モードは opt-in
- **多モデル並列実行による応答遅延** → 並列起動 + タイムアウト設定 + リトライ上限 (max 2 回) で吸収
- **観点ファイル `.test-brainstorm.md` の Git 漏洩**: 内部設計や脆弱性発想が含まれるため、デフォルトで `.gitignore` 対象とし、共有時のみ明示的にコミット

## 関連

- [ADR-0001](0001-multi-llm-development-workflow.md): 前提となるレビュー多モデル化方針
- [docs/design/multi-model-test-pipeline.md](../design/multi-model-test-pipeline.md): 実装計画
- [docs/setup/local-llm.md](../setup/local-llm.md): vLLM セットアップ手順 (本 ADR 採択後に更新)
- 関連スキル: `/test-generate` `/test-data` `/local-review` `/deepseek-redteam`

## 改訂履歴

- 2026-05-24 提案 (未採択)
- (採択時) 採択日記入、関連 Linear Project へリンク
