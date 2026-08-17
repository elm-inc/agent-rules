# ADR-0001: AI 開発ワークフローを多層・多モデル化する

## ステータス

**Superseded by [ADR-0017](0017-ai-workflow-model-refresh-and-review-layers.md) (2026-08-17)** — 採択 (2026-05-22)

> 決定内容は当時の記録として残す。現行の役割分担・モデル選定は ADR-0017 を参照。

## 文脈

agent-rules リポジトリでは AI スキル群を継続的に追加・運用している。当初は Claude Opus 4.7 を主軸に Codex CLI (OpenAI) によるセカンドオピニオン構成だったが、以下の課題が顕在化した:

- **AI 比率の上昇**: 開発・レビュー・検証を AI に任せる割合が増え、単一モデル依存が品質の単一障害点になりつつある
- **Groupthink リスク**: Claude (Anthropic) と GPT (OpenAI) は学習分布が近く、同じ系統の見落とし方をする傾向
- **コスト/速度のトレードオフ**: クラウド API は高速だが従量課金、ローカルは無料だが速度面の制約
- **機密性レベルの不均一**: 公開コードと業務コードで送信可否の判断基準が必要

これらに対応するため、AI 開発ワークフローを **多層化** し、**異種ベンダー** および **ローカル LLM** を組み合わせる方針を採る。

## 決定

### 1. 役割分担を明示し、複数 LLM を併用する

| ロール | モデル / ツール |
|---|---|
| 実装 (主) | Claude Opus 4.7 (Claude Code 本体) |
| 0 次レビュー | ローカル Qwen2.5-Coder-32B (vLLM/FP8) |
| セカンドオピニオン | Codex (GPT-5) |
| 設計レッドチーム | DeepSeek-R1 (思考連鎖 API) |
| リポ横断レビュー | Gemini 2.5 Pro (1M context) |
| テスト生成 | Qwen (主) + DeepSeek-R1 (property 発想) |
| テストデータ | Qwen (バッチ推論) |
| 機械検証 | pre-commit hooks (ruff/mypy/semgrep/type-check) |

### 2. 5 つの新規スキルを agent-rules リポに追加

- `/local-review` `/deepseek-redteam` `/gemini-review` `/test-generate` `/test-data`
- 既存 `/codex-review` `/codex-audit` `/codex-task` は維持

### 3. 機密情報の取扱いポリシー

- ローカル Qwen は無制限利用可
- クラウド (Gemini / DeepSeek) は公開 OSS および差分レベルの送信に留め、機密コードはローカル優先
- API キーは `~/.bashrc` に直接書かず `~/.*_token` (perms 600) ファイルから読み込み

## 理由

### Why 異種ベンダー混合

Claude と GPT は学習データと RLHF 手法が近く、**同じ間違い方をする傾向** がある。実際に Phase 4 試運転で:
- Claude/Codex は **個別ファイル内の問題** は確実に検出
- Gemini は **cross-file の型不整合や drift** を唯一発見
- DeepSeek-R1 は **設計上の致命的問題** (Redis SPOF、HS256 vs RS256) を提案

異なる訓練系統のモデルを混ぜることで、視点の多様性が品質保証の独立性を担保する。

### Why ローカル LLM 導入

- **コスト 0**: 頻度の高い 0 次レビューを無限に回せる
- **機密性**: ネットワーク経由でコード送信しない安心感
- **常時稼働**: API レート制限の影響を受けない
- **GPU 投資の活用**: RTX PRO 4500 Blackwell (32GB) を遊ばせない

### Why 機械検証 (非 AI) 併用

LLM レビューは確率的で見逃しがあるため、決定論的な検証層が必須。型システム、linter、semgrep 等は AI と独立して動作するため、3 層 (機械・LLM・人間) で冗長性を確保する。

## 検討した代替案

### 代替案 A: 単一クラウド LLM に集約 (Claude のみ)
- Pros: 運用シンプル、コンテキスト連続性、コスト見通し容易
- Cons: 単一障害点、groupthink リスク、機密データ送信不可、レート制限影響
- 不採用理由: AI 比率上昇前提と矛盾

### 代替案 B: 巨大ローカルモデルに集約 (DeepSeek-V3 671B 等)
- Pros: 完全オンプレ、コスト 0、機密 OK
- Cons: 32GB VRAM では動作不可 (DeepSeek-V3 は Q2 でも 200GB+)、複数 GPU 必要
- 不採用理由: ハードウェア制約

### 代替案 C: スキル統合 (`/review` 1 つで全 LLM 並列実行)
- Pros: ユーザーインターフェース単一
- Cons: 用途別の使い分けが不明確、コスト最適化困難
- 不採用理由: 現状は用途別の方が ROI 可視化しやすい。`/multi-review` として将来検討余地あり

## 帰結

### Pros

- 単一モデル依存を排除、品質保証の冗長性確保
- ローカル LLM で 0 次チェックを無限回せる安心感
- DeepSeek-R1 の高 ROI (7 円で critical 発見)
- Gemini の cross-file 視点で固有の不具合を検出可能
- 機密データのリスク低減 (ローカル経路の選択肢)

### Cons

- 運用複雑性の増加 (5 つの新規スキル、3 種のクラウド API キー管理)
- ローカル LLM のセットアップコスト (vLLM + Qwen 構築、CPU offload 等のチューニング)
- 推論速度のばらつき (Qwen は 6 tokens/sec で遅め、Phase 6+ で改善)
- 月額追加コスト (Gemini + DeepSeek で $2-3 / 開発者・月の想定)
- 組織コンプライアンス整理が必要 (特に DeepSeek 中国経由の利用範囲)

### 引き受けるリスク

- LLM の出力品質劣化リスク → ROI 評価を月次で実施 (Phase 6 月次更新)
- ベンダーロックイン回避が目的だが、運用負担とのバランスを継続評価
- スキル間の責務重複 → 1-2 ヶ月運用後に整理 (本 ADR を見直し or 新 ADR で上書き)

## 関連

- [docs/design/ai-workflow.md](../design/ai-workflow.md): 設計詳細・実績データ
- Linear Project: [AI 開発ワークフロー多層化](https://linear.app/elm-inc/project/ai-開発ワークフロー多層化-5d5bc734ffcd)
- 主要コミット: b5e202c (Phase 1 主実装), c5ab497 (Phase 2 vLLM), 0615b83 (Phase 3 API)

## 改訂履歴

- 2026-05-22 採択 (Phase 1-5 完了時点)
- (将来) 3 ヶ月運用後の振り返りで Supersede 検討
