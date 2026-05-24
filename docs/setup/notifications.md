# Push 通知セットアップ (vLLM healthcheck → iPhone)

AGENT-15 で確立。`scripts/vllm-healthcheck.sh` (AGENT-12 で作成) を cron から定期実行し、vLLM ダウン時に iPhone に push 通知する手順。

## なぜ ntfy.sh か

- **無料** (個人利用)
- **アカウント不要**: トピック名さえ知っていれば誰でも publish/subscribe できるシンプルな仕組み
- **iPhone 公式アプリあり**: [ntfy](https://apps.apple.com/app/ntfy/id1625396347)
- **CLI 連携が curl 1 本**: 既存 healthcheck スクリプトに数行追加するだけ
- 軽量代替: Slack Incoming Webhook / Discord Webhook も同パターンで併用可

## セキュリティモデル

ntfy.sh の公開トピックは **トピック名 = 実質パスワード**。誰でも知っていれば publish も subscribe もできる。よって:

- **推測されない長文字列を使う**: 例 `elmo-vllm-9k3m2p7q5x8c` (英数字 16+ 文字)
- **公開リポにトピック名を書かない**: 本ドキュメントの `CHANGEME` 部分を実トピックに置き換える際、リポにコミットしない
- 機密度が高ければ self-hosted ntfy.sh (Docker で 5 分で立つ) も検討

## セットアップ手順

### 1. iPhone 側

1. App Store で **ntfy** をインストール
2. アプリを起動、+ ボタン → "Subscribe to topic"
3. Server: `ntfy.sh` (デフォルト)
4. Topic: 自分で決めた推測されない名前 (例 `elmo-vllm-9k3m2p7q5x8c`)
5. 通知許可を ON
6. (任意) Topic 設定 → "Default priority" を High に → ロック画面表示

### 2. Linux 側: NTFY_TOPIC を環境変数化 (機密ファイル経由)

API キー方式 ([[api-token-file-pattern]]) に揃え、トークンを直接 `~/.bashrc` に書かない:

```bash
echo "elmo-vllm-9k3m2p7q5x8c" > ~/.ntfy_topic
chmod 600 ~/.ntfy_topic
```

そして `scripts/env-snippet.sh` (既存) に以下を追記してから `source ~/.bashrc`:

```bash
[ -f ~/.ntfy_topic ] && export NTFY_TOPIC="$(cat ~/.ntfy_topic)"
```

### 3. 動作確認 (通知が iPhone に届くか)

```bash
# 手動 publish
curl -d "test from $(hostname) at $(date)" "https://ntfy.sh/$NTFY_TOPIC"
# → 数秒以内に iPhone に通知が来れば OK
```

### 4. cron 登録

```bash
# 現在の crontab に行を追加 (CHANGEME 部分をエディタで実トピックに置換)
crontab -l 2>/dev/null > /tmp/crontab.bak
{
  crontab -l 2>/dev/null
  echo ""
  echo "# vLLM healthcheck (AGENT-15)"
  echo "*/5 * * * * NTFY_TOPIC=$(cat ~/.ntfy_topic) /home/elmo/repos/github.com/elm-inc/agent-rules/scripts/vllm-healthcheck.sh"
} | crontab -

# 登録確認
crontab -l | tail -5
```

または `templates/cron/vllm-healthcheck.crontab` をコピーしてエディタで `CHANGEME` 部分を実トピックに置き換えてから:

```bash
cat templates/cron/vllm-healthcheck.crontab | sed "s/CHANGEME/$(cat ~/.ntfy_topic)/" | crontab -l 2>/dev/null > /dev/null
# (append append のため工夫が必要、上の手動方式が簡単)
```

### 5. E2E 確認 (vLLM 停止 → 通知)

```bash
# vLLM を 5 分以上停止 (cron が次に走るまで)
docker stop vllm-qwen-coder

# 5 分待つ
sleep 360

# iPhone に「vLLM unhealthy on <host>: ...」通知が来るはず

# 復帰
docker start vllm-qwen-coder
```

E2E 確認後、cron 起動間隔やフィルタを調整。

## 通知ストーム対策

`vllm-healthcheck.sh` は毎回失敗時に通知するため、長時間ダウン時に **5 分おきに通知が来る = うるさい**。対策案:

- **silence file**: スクリプトに「直近 N 分以内に通知済みなら skip」を追加 (`/tmp/vllm-healthcheck-last-notify` の mtime チェック)
- **escalation only**: 1 回目だけ通知、復旧時に「resolved」通知

実装は別 Issue (AGENT-15 完了後に運用してから判断)。

## Claude Code の Mobile Push との使い分け

[Remote Control + 公式 Claude アプリ](https://code.claude.com/docs/en/remote-control.md) は **Claude セッションが押したい時に push** する仕組み (permission 待ち、長時間タスク完了など)。一方、本 ntfy.sh は **サーバ死活監視** で常時走る背景監視。

| 用途 | 推奨経路 |
|---|---|
| Claude セッションの permission 待ち / 完了 | Remote Control (公式アプリ) |
| vLLM/サーバの死活監視 | ntfy.sh + cron (本ドキュメント) |
| Slack/Discord に集約したい | `WEBHOOK_URL` を `vllm-healthcheck.sh` 側で活用 |

両者を **同じ iPhone アプリで受けない** ことに注意 (ntfy は ntfy アプリ、Remote Control は Claude アプリ)。

## 関連

- スクリプト: [`scripts/vllm-healthcheck.sh`](../../scripts/vllm-healthcheck.sh)
- crontab テンプレ: [`templates/cron/vllm-healthcheck.crontab`](../../templates/cron/vllm-healthcheck.crontab)
- ADR-0001 / 0002: ローカル LLM の稼働保証はワークフロー全体の前提
- [[api-token-file-pattern]] memory: `~/.*_token` 600 権限ファイル方式
