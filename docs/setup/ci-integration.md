# CI 統合: /local-review を GitHub Actions で自動実行

AGENT-17 で確立した手順。PR opened/synchronize で `/local-review` 相当を自動実行し、結果を PR コメントに貼る。

## なぜ self-hosted runner が必要か

ローカル vLLM (`http://localhost:8000`) は GitHub-hosted runner からは到達不可。**self-hosted runner を vLLM ホスト (elmo machine) と同じマシン上で起動**する必要がある。

代替案として Tailscale で tailnet を作り、GitHub-hosted runner から Tailscale 経由でアクセスする方法も理論的には可能だが、Tailscale サブスクリプション + 設定の複雑化と引き換えなので **self-hosted 同居が最も単純**。

## セットアップ手順

### 1. self-hosted runner のインストール (elmo machine)

各リポジトリ単位 or 組織レベルで runner を登録できる。複数リポで共有するなら**組織レベル登録**を推奨:

```bash
# 1) GitHub UI で取得: Settings → Actions → Runners → "New self-hosted runner"
#    OS=Linux x64 を選択 → 表示されるトークンを使う

mkdir -p ~/actions-runner && cd ~/actions-runner
curl -O -L https://github.com/actions/runner/releases/download/v2.319.1/actions-runner-linux-x64-2.319.1.tar.gz
tar xzf actions-runner-linux-x64-2.319.1.tar.gz

# 2) 組織レベル登録 (推奨)
./config.sh --url https://github.com/elm-inc \
  --token <ORG_LEVEL_TOKEN> \
  --labels vllm,linux,x64 \
  --name elmo-vllm-runner

# 3) systemd unit 化して常駐起動
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

`--labels vllm` が **重要**: ワークフロー (`local-review.yml`) は `runs-on: [self-hosted, vllm]` でこの label を指定する。

### 2. runner ホストの前提確認

```bash
# vLLM が稼働しているか
curl -sf http://localhost:8000/v1/models | jq .

# jq / gh CLI / curl がインストール済みか (workflow が使用)
which jq gh curl

# gh が認証済みか (runner は内蔵の GITHUB_TOKEN を使うので通常 OK)
```

### 3. ワークフローをリポにコピー

リポの root で:

```bash
mkdir -p .github/workflows
cp ~/repos/github.com/elm-inc/agent-rules/templates/.github/workflows/local-review.yml \
   .github/workflows/

git add .github/workflows/local-review.yml
git commit -m "ci: add /local-review automation (agent-rules AGENT-17)"
git push
```

### 4. 試運転

任意の小さい PR を 1 つ作って動作確認。PR コメントに「🤖 /local-review (Qwen-Coder-32B FP8, AGENT-17)」が貼られれば成功。

```bash
gh pr create --title "test: ci-integration trial" --body "AGENT-17 試運転"
# → 数十秒〜2 分で PR コメント
```

## ワークフローの仕様

- **トリガー**: `pull_request` の `opened` / `synchronize` / `reopened`
- **safety**:
  - `if: github.event.pull_request.draft == false` でドラフト PR を skip
  - diff > 80,000 bytes (~20K tokens) なら skip (Qwen mml=4096 制約)
  - 空 diff なら skip
  - `concurrency.cancel-in-progress: true` で同 PR の旧ジョブを止める (節約)
- **コスト**: 0 (ローカル GPU の電気代のみ、Qwen-Coder-32B FP8 で約 60s/レビュー)
- **コメント**: `permissions.pull-requests: write` + 組込 `GITHUB_TOKEN` で gh CLI 経由

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| ジョブが起動しない | runner の label `vllm` が `runs-on` と一致してるか確認、`sudo ./svc.sh status` |
| `local vLLM is unreachable` | vLLM コンテナ停止中 (`docker ps | grep vllm-qwen-coder`)、再起動: `docker start vllm-qwen-coder` |
| `diff > 80K bytes, skipping` | 大規模 PR は手動 `/local-review --base main` をファイル単位で実行 |
| コメント投稿失敗 | リポ設定で Actions の write permission が無効化されていないか確認 (Settings → Actions → General → Workflow permissions) |
| swap で vLLM 停止中の PR | `/test-generate --brainstorm --with-distill` 実行中などで vLLM が swap されていると失敗。再 push でリトライ、or AGENT-17 を `vllm-swap-to.sh status` 確認後に手動キック |

## 他 CI スキルとの組み合わせ

- 本ワークフロー = **0 次レビュー** (Qwen ローカル)
- 必要に応じて手動で `/codex-review` `/gemini-review` `/deepseek-redteam` を続行
- 全レイヤを CI 化したい場合は `templates/.github/workflows/` に類似 yml を追加 (Codex/Gemini はクラウド runner で OK)

## 関連

- ワークフロー雛形: `templates/.github/workflows/local-review.yml`
- ローカル LLM セットアップ: `docs/setup/local-llm.md`
- /local-review スキル: `skills/local-review/SKILL.md`
- ADR-0001: `docs/adr/0001-multi-llm-development-workflow.md`
