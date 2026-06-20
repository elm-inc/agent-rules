# 多並行セッション管理ランブック

同一プロジェクトの並列タスク (git worktree) と複数プロジェクトを、Claude Code セッションを多数 (5〜10+) 開いて進めるときの運用。「どれが自分の入力待ちか分からず管理しきれない」を解消するのが目的。

## 基本方針

**10 窓を前に並べて巡回しない。1 つのハブで状態を見て、入力が要るものだけに介入する。**

3 つの集約を役割分担で使う:

| 見たいもの | ツール | 何が分かるか |
|---|---|---|
| **各セッションのライブ状態** | `claude agents` (Agent View) | 全セッションを「入力待ち / 実行中 / 完了」でグループ表示。ここから新規ディスパッチも。**ハブはこれ** |
| **同一プロジェクトの並列タスク構造** | `/worktree-list` | worktree ごとのタスク・変更状況・衝突リスク (`<repo>/.git/parallel-tasks.json` レジストリ) |
| **プロジェクト横断のリポ状態** | `/status` | elm-inc 全リポの最近の commit / open PR・Issue / memory / 未コミット変更 |

`claude agents` = 今どれが自分を待っているか、`/worktree-list` = タスクの全体像、`/status` = リポの状態。

## セッションの一覧・切替・命名

- **`claude --resume`**: セッションピッカー (名前・ブランチ・最終更新・メッセージ数)。`Ctrl+W`=全 worktree / `Ctrl+A`=全プロジェクト / `Ctrl+B`=ブランチ絞り / `/`=検索。← この 2 軸切替がまさに今回の用途
- **`/resume`**: セッション内から別セッションへ切替
- **`claude --continue`**: そのディレクトリの直近セッションを再開
- **命名 (重要)**: ピッカー/Agent View を読みやすくするため必ず名前を付ける
  - worktree 並列セッション: `/worktree-start` 経由で起動 (`claude --remote-control "<タスク名>"`) すれば**タスク名付き**になる
  - プロジェクト横断のセッション: **`/rename <プロジェクト:タスク>`** で命名 (例 `tamayori:persona実装`)

## 子守りをやめる (通知)

見張らずに済むよう、**入力待ち/完了したら通知**させる:

- **手元のデスクトップ/ターミナル通知 (本リポ同梱)**: `Notification` フック `scripts/claude-notify.sh` を `~/.claude/settings.json` に登録すると、入力待ち/許可確認の時にプロジェクト名付きでデスクトップ通知 (Linux/libnotify) + ターミナル通知 + ベルが鳴る。matcher は `permission_prompt|idle_prompt`。登録スニペットはスクリプト先頭に記載
- モバイル push: `settings.json` の `agentPushNotifEnabled` が true なら有効。`/config` →「Push when Claude decides」で「判断が要る時/長時間タスク完了時」に iPhone へ
- 外出先からは **Remote Control** (`claude remote-control`、iPhone/Android の Code タブ) で全セッションを状態ドット付きで一覧・操作

→ 通知が来たセッションだけ `claude agents` から開いて対応する。

## セッションを増やしすぎない (根本対策)

別セッションが正解なのは**協調不要の独立並列**だけ。新しい窓を開く前に:

- **片手間の探索・調査は新窓を開かず、サブエージェント** (`explorer`/`researcher`, Haiku) に委譲して**今のセッション内**で済ます
- worktree 運用の原則は「**デフォルトは単一セッション**」(同一セッション内で `cd <worktree>` して作業 → メインに戻り `/worktree-finish`)。真に同時進行が要る独立タスクだけ別セッションにする
- 並列分解は最大 5 を目安 (>10 は無益。標準オーケストレーション参照)
- 完了した worktree は `/worktree-finish` で畳む。古いセッションは `cleanupPeriodDays` (既定 30 日) で自然消滅するが、不要な窓は閉じる

## 推奨デイリーフロー

1. 開始時: `/status` で全体把握 → `claude agents` で各セッションの状態確認
2. 新規タスク: 独立並列が必要か判断 (不要なら subagent/単一セッション)。必要なら `/worktree-start <名> <説明>`、横断作業は `/rename` で命名
3. 進行中: 窓を巡回せず、通知 or `claude agents` の「入力待ち」だけに対応
4. 完了: `/worktree-finish` でマージ・片付け

## 端末多重化 (zellij) のセッション衛生

Claude 側を整えても、zellij のセッションが別レイヤーで溜まる。たまり方は 2 種類で対処が違う:

- **① EXITED (死骸 / resurrect 待ち)**: 中身は終了済みだが `session_serialization` (既定 on) が復活用にキャッシュへ残す。純粋なゴミ
- **② 実行中の detach セッション**: 中で shell/claude が生きている。一括 kill は危険

運用:

- **ハブは session-manager** (`Ctrl+o w`): 全セッションを一覧・切替・kill。`claude agents` と同じ「窓を巡回しない・ハブで見る」発想を端末側にも適用する
- **命名で増殖を止める**: 裸の `zellij` 起動はランダム名 (`kind-panda` 等) を量産し、attach せず再起動すると `scm` / `scm-2` のような重複ができる。`zj [名]` (= `zellij attach --create`、引数省略時はカレントディレクトリ名) で **プロジェクト = セッション 1 つ**に集約。さらに**裸 `zellij` (引数なし) 自体も関数ラップで `zj` に流す**ので、`zj` と打たなくても cwd 名セッションに集約される。`list-sessions` 等サブコマンド付きは素通し、ランダム名で新規が欲しいときだけ `command zellij`
- **worktree を別タブで着手 (引き継ぎ付き)**: `/worktree-start <名> <説明> --tab` で worktree を cwd にした zellij 新タブを開き、cd して**引き継ぎドキュメント** (`<共有.git>/worktree-tasks/<ID>-<名>.md` に ID 付きで集約・永続) を初期プロンプトに渡して `claude` を自動起動。子が親の意図・方針を引き継いで着手する。別 zellij セッションより軽い「真の並列」着手
- **死骸を一掃**: `zjreap` (= `zellij delete-all-sessions -y`) は **EXITED だけ削除し実行中は触らない** (安全)。個別 kill は `zellij kill-session <名>`
- **そもそも溜めたくない場合**: `~/.config/zellij/config.kdl` で `session_serialization false` にすると EXITED を残さない (resurrect 機能は失う)
- ヘルパー `zj` / `zjreap` / `zjls` は `~/.bashrc` に定義済み

## 参照

- Agent View: https://code.claude.com/docs/en/agent-view
- Sessions (resume/rename/picker): https://code.claude.com/docs/en/sessions
- Remote Control: https://code.claude.com/docs/en/remote-control
- 自前スキル: `/status`, `/worktree-list`, `/worktree-start`, `/worktree-finish`
