# Phase 3: クラウド LLM API セットアップ実行記録

Linear: [AGENT-3](https://linear.app/elm-inc/issue/AGENT-3)
Branch: `worktree/agent-3-phase3-cloud-api`
Started: 2026-05-22

## 採用方針

- API キーは `~/.bashrc` に直接書かず `~/.*_token` ファイル (perms 600) に保存
- `scripts/env-snippet.sh` が起動時にファイルから読み込み環境変数化
- 理由: シェル設定ファイルのバックアップ漏洩、他プロセスからの読取り可能性を最小化

## API キー取得手順 (実施済)

### Gemini
1. https://aistudio.google.com/apikey で API key 作成
2. https://ai.studio/projects で Billing 設定 (Prepay $10 を入金)
3. キーを `~/.gemini_token` に保存 (perms 600)

> 注意: Gemini API には 2 つの billing 方式あり
> - **Standard (post-paid)**: GCP 連携、使った分だけ後請求、上限要監視
> - **Prepay (前払い)**: 残高超えで自動停止、安全 (採用)

### DeepSeek
1. https://platform.deepseek.com/api_keys でキー作成
2. https://platform.deepseek.com/top_up で $2 入金 (Stripe)
3. キーを `~/.deepseek_token` に保存 (perms 600)

## 動作確認結果 (2026-05-22 19:0X)

### Gemini 2.5 Pro

```
プロンプト: 1から10までの素数を3行で列挙してください
入力: 13 tok, 出力: 27 tok, 思考: 1448 tok, 計: 1488 tok
応答時間: 12.97s
終了理由: STOP (正常)
```

**気付き**: Gemini 2.5 Pro は **thinking モードがデフォルト有効**で、簡単な質問でも 1448 思考 token を消費した。
- `/gemini-review` で 500K input + thinking + 出力なら 1 回当たり実際は予想の数倍コストかも
- 単価: input $1.25/M, output $10/M, **thinking は output 扱いで $10/M**
- 上記テスト: 概算 $0.015 / 1 リクエスト (1.5 円)
- Phase 5 で `thinkingConfig: {thinkingBudget: 0}` で thinking 無効化検討可

### DeepSeek-R1 (deepseek-reasoner)

```
プロンプト: 1から10までの素数を3行で列挙してください (同じ)
入力: 16 tok, 出力: 32 tok, 思考: 990 tok 程度, 計: 1038 tok
応答時間: 16.91s
正常応答 + reasoning_content (思考過程) 両方取得確認
```

**気付き**: R1 の思考連鎖は長め (簡単な質問で 47 行)。実用ではプロンプトで「簡潔に」と明示推奨。
- 単価: input $0.55/M, output $2.19/M (含思考)
- 上記テスト: 概算 $0.002 / 1 リクエスト (0.3 円) — 約 5 倍安い

## 完了条件チェック

- [x] `/gemini-review` 動作確認 (gemini-2.5-pro で応答取得)
- [x] `/deepseek-redteam` 動作確認 (deepseek-reasoner で reasoning + 応答取得)
- [x] エラーなく実行できる
- [ ] 機密情報送信ポリシー (組織判断、後日確認推奨)

## ユーザー残作業

1. `scripts/env-snippet.sh` の内容を `~/.bashrc` 末尾に追加 → `source ~/.bashrc`
2. (推奨) 課金監視
   - Gemini: GCP コンソール → 課金 → 予算アラート設定
   - DeepSeek: dashboard で残高チェック頻度を決める
3. (組織判断) 機密性レベル定義
   - 公開 OSS のみクラウド OK
   - 業務コードはローカル (`/local-review`) のみ
   - 等のポリシー文書化

## 単価まとめ

| API | input $/M | output $/M | 試算 (1 リクエスト) |
|---|---|---|---|
| Gemini 2.5 Pro | $1.25 (≤200K) / $2.50 (>200K) | $10 (含 thinking) | $0.01-0.05 |
| DeepSeek-R1 | $0.55 | $2.19 (含思考) | $0.002-0.01 |

`/gemini-review` のリポ横断 (500K tokens 投入時) は単発 $5-10 程度を覚悟。
`/deepseek-redteam` は頻発しても月数百円で収まる想定。

## Phase 5 への引継ぎ

1. Gemini thinking budget の最適化 (`/gemini-review` で必要に応じ無効化)
2. DeepSeek-R1 の出力簡潔化プロンプト工夫
3. コスト集計 (1 ヶ月後)

## 生成済みアーティファクト

- `scripts/test-gemini.sh` — 動作確認 + 思考 tokens 表示
- `scripts/test-deepseek.sh` — reasoning_content + 最終応答表示
- `scripts/env-snippet.sh` — 全 API キーをファイルから安全に読み込み
