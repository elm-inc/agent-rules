# ADR-0005: ローカル LLM (vLLM) を常駐からオンデマンド起動に変更する

## ステータス

採択 (2026-06-11)

ADR-0001 / ADR-0002 で定めた「主力 Qwen-Coder-32B FP8 を**常駐**、swap 候補を要求時起動」という運用方針のうち、**常駐**部分を Supersede する。多層・多モデルの役割分担そのものは維持する。

## 文脈

`/local-review` `/test-generate` `/test-data` が前提とする vLLM (Qwen2.5-Coder-32B FP8) を、`vllm-qwen-coder.service` (systemd, boot 自動起動) として**常駐**させていた。常駐は以下の前提で妥当だった: ローカル LLM 系スキルを高頻度で使い、起動レイテンシ (モデルロード 1-2 分) を都度払いたくない。

しかし運用してみると、GPU は 1 枚 (RTX PRO 4500, 32GB) であり、vLLM が ~16GB+ を**常時占有**するため、同じマシンで GPU を使う他プロジェクト (学習・別の推論・実験) を動かすたびに `systemctl stop` で手動停止し、終わったら再起動する手間が発生していた。ローカル LLM スキルの実利用は「コミット前」などに集中し、GPU 占有時間の大半はアイドルだった。

## 決定

vLLM を**オンデマンド起動 + アイドル自動停止**に変更する。常駐 (boot 自動起動) はやめる。

### 1. オンデマンド起動 (`scripts/ensure-vllm.sh`)

ローカル LLM 系スキルは推論前に `ensure-vllm.sh` を呼ぶ。冪等で、稼働中なら即進行、未稼働なら起動して `/v1/models` が healthy になるまで待機する。docker を直接管理し (elmo は docker グループ所属のため **sudo 不要**)、コンテナ設定は常駐時と同一 (`--max-model-len 4096 --gpu-memory-utilization 0.88 --cpu-offload-gb 6 --enforce-eager`, HF cache は `~/.cache/huggingface`)。

### 2. アイドル自動停止 (`scripts/vllm-idle-watch.sh`)

`ensure-vllm.sh` は起動時にアイドル監視を 1 つ常駐させる (`flock -n` で多重起動防止、`setsid` で完全デタッチ、各スキル呼び出し時に死活確認して self-healing で再起動)。監視は vLLM の Prometheus メトリクス `vllm:prompt_tokens_total` (単調増加カウンタ) を poll し、一定時間 (デフォルト `VLLM_IDLE_MINUTES=15`) 変化が無く実行中リクエストも 0 なら `docker stop` して GPU を解放する。スキル経由でも直接 API 利用でも全リクエストを取りこぼさず検知する。

### 3. 常駐 systemd からの移行

一度だけ `sudo systemctl disable --now vllm-qwen-coder` を実行して boot 自動起動と現行常駐を止める。systemd unit (`templates/systemd/vllm-qwen-coder.service`) は**残す** — 高頻度利用が常態化したマシンでは常駐 (旧方式) を選べる。オンデマンドを既定とし、常駐は opt-in とする。

## 根拠

- **GPU を普段解放**: 他プロジェクトの GPU 利用時に手動停止が不要になる (本 ADR の主目的)
- **手間の除去**: アイドル自動停止により「使い終わったら止める」を人手で行わずに済む
- **sudo 不要**: docker グループ権限で完結し、スキルから非対話で起動・停止できる
- **設定の一貫性**: 常駐時と同一の docker 設定・HF cache パスを使い、挙動差を生まない

## トレードオフ / 不採用案

- **コスト**: アイドル後の初回スキル実行は**モデルロード待ち (1-2 分)** が入る。連続実行や 15 分以内の再実行はキャッシュ済みで即時。即 GPU を空けたい時は `ensure-vllm.sh stop`。
- **systemd socket activation は不採用**: 30B FP8 のロードに分単位かかるため、最初の接続をブロックして待たせる socket activation は UX (進捗表示・タイムアウト制御) が劣る。スクリプトでの明示的な起動待ちを採る。
- **swap 方式 (ADR-0002) との関係**: `/test-generate --with-distill` の一時 swap は、復帰を `docker start` から `ensure-vllm.sh` に変更 (常駐コンテナが `--rm` で消えるため)。swap 自体の役割分担は不変。

## 影響範囲

- 追加: `scripts/ensure-vllm.sh`, `scripts/vllm-idle-watch.sh`
- 変更: `skills/local-review`, `skills/test-generate`, `skills/test-data` の起動保証ステップ / `docs/setup/local-llm.md` / `scripts/vllm-swap-to.sh` (restore を `docker start` から `ensure-vllm.sh` 経由に変更)
- 不変 (opt-in 化): `templates/systemd/vllm-qwen-coder.service`, `scripts/vllm-healthcheck.sh`

## 追記 (2026-06-12 — Fable 5 最終レビュー反映)

実装後の最終レビューで以下を是正・補強した (決定は不変、実装詳細の確定):

- **常駐 (opt-in) との共存**: `ensure-vllm.sh` / `vllm-idle-watch.sh` は `systemctl is-active --quiet vllm-qwen-coder` を判定し、systemd 管理下では起動・停止・watcher に干渉せず healthy 確認のみ行う (相互 churn を防ぐ)。
- **swap restore の整合**: 主力は `--rm` 撤去後も停止中=コンテナ不在のことがあるため、`vllm-swap-to.sh restore` は `docker start` ではなく `ensure-vllm.sh` で復帰する。
- **`--rm` 撤去**: 異常終了 (GPU 競合/OOM) 時の `docker logs` を保全するため `docker run --rm` をやめ、起動前の `docker rm -f` で掃除する方式に統一。
- **cold-start の直列化**: worktree 並列での同時起動による殺し合いを防ぐため up 経路を `flock` で直列化し、ロック取得後に healthy を再チェックする。

## 関連

- ADR-0001 (multi-LLM ワークフロー), ADR-0002 (multi-model test generation) — 役割分担は維持、常駐部分のみ更新
- [`docs/setup/local-llm.md`](../setup/local-llm.md) — 運用手順
