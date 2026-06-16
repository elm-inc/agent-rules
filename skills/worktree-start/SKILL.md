---
name: worktree-start
description: 並列開発用の git worktree を作成し、タスクをレジストリに登録する。新しいタスクを並列で始めたい、worktree を作りたいときに使用
argument-hint: "<タスク名> <タスクの説明> [--linear <ID>] [--no-remote] [--tab]"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(jq *) Bash(cat *) Bash(mkdir *) Bash(date *) Bash(zellij action *) mcp__linear__* Read Write
---

# 並列開発: worktree 作成とタスク登録

git worktree を作成し、並列開発タスクをレジストリに登録する。Linear Issue ID を指定すれば、ブランチ名に ID を埋め込み、Linear 側の状態を In Progress に遷移させる。

## 引数の解釈

`$ARGUMENTS` を以下のように解釈する:
- 第1トークン → タスク名（ブランチ名のサフィックスにも使用。例: `feat-auth`）
- 残り → タスクの説明（例: `ユーザー認証機能の追加`）
- `--linear <ID>`: Linear Issue ID (例: `ELM-123`)。指定すると:
  - ブランチ名が `worktree/<linear-id-lowercase>-<タスク名>` になる (Linear 側で PR 自動紐付け)
  - Linear Issue を In Progress に遷移
  - `parallel-tasks.json` に `linear_issue_id` を記録
- `--no-remote`: Remote Control 付き起動コマンドを案内しない。指定しない場合 (デフォルト) は最終案内に `claude --remote-control "<タスク名>"` を含める (iPhone 公式 Claude アプリの Code タブから push 通知・状態確認可能)
- `--tab`: zellij セッション内 (`$ZELLIJ` が設定されている) なら、worktree を cwd にした新しい zellij タブを開き、worktree へ cd して、**引き継ぎドキュメント (手順4) を初期プロンプトに渡して** `claude` を自動起動する (Enter まで送出)。zellij 外では無視して従来の案内に戻す

なお `--tab` の有無にかかわらず、毎回タスク引き継ぎドキュメント (B+D) を `<共有.git>/worktree-tasks/<ID>-<タスク名>.md` に作成する (手順4)。docs/ を汚さず中央フォルダに ID 付きで集約し、タスク完了後も残す。

タスク名が未指定の場合はユーザーに確認する。Linear 運用ポリシー (project_linear_workflow メモリ) に従い、ステークホルダー可視化が必要な作業は `--linear` を付ける。

## 実行手順

### 1. 前提確認
- 現在のディレクトリが git リポジトリ内であることを確認
- メインワークツリーのルートパスを取得:
  ```bash
  MAIN_WORKTREE=$(git worktree list --porcelain | head -1 | sed 's/worktree //')
  ```
- 共有 git ディレクトリを取得:
  ```bash
  GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
  ```

### 2. worktree 作成
- ベースブランチ（現在のブランチ）を記録
- worktree のパスは `<メインワークツリーのパス>-worktrees/<タスク名>/`
- ブランチ名:
  - `--linear <ID>` 指定なし: `worktree/<タスク名>`
  - `--linear <ID>` 指定あり: `worktree/<ID-lowercase>-<タスク名>` (例: `worktree/elm-123-feat-auth`)
  ```bash
  WORKTREE_BASE="${MAIN_WORKTREE}-worktrees"
  mkdir -p "$WORKTREE_BASE"
  git worktree add "${WORKTREE_BASE}/<タスク名>" -b "<ブランチ名>"
  ```

### 3. Linear Issue 連携 (--linear 指定時のみ)
- Linear MCP の `get_issue` 相当で Issue が存在することを確認
- 既に Done/Cancelled なら警告して中断 (`--force` で続行可)
- `update_issue` 相当で state を `In Progress` (`Started`) に遷移
- Issue の Assignee が未設定なら自分にアサイン
- Issue URL を控えてレジストリと最終案内に含める

### 4. タスク引き継ぎドキュメント作成 (B+D)

別タブ/別セッションの子 Claude に親の意図・方針を引き継ぐためのドキュメントを、**中央フォルダに ID 付きで**作成する (docs/ には置かない＝散乱防止、タスク完了後も削除しない)。子は新規セッションで親の会話・プランを自動継承しないため、これが引き継ぎの本体になる。

- 保存先フォルダ: `${GIT_COMMON_DIR}/worktree-tasks/` (git 管理外・全 worktree から `git rev-parse --git-common-dir` で同一パス参照・永続)
- タスク ID: `date +%Y%m%d-%H%M%S` (例 `20260616-094530`、ソート可能で一意)
- ファイル: `${GIT_COMMON_DIR}/worktree-tasks/<ID>-<タスク名>.md`
  ```bash
  TASK_ID=$(date +%Y%m%d-%H%M%S)
  TASKS_DIR="${GIT_COMMON_DIR}/worktree-tasks"
  mkdir -p "$TASKS_DIR"
  TASK_DOC="${TASKS_DIR}/${TASK_ID}-<タスク名>.md"
  ```
- 内容は **Write ツール**で以下の雛形を埋めて書く。親セッションで着手しようとしていたタスク・方針・決定を盛り込み、詳細は散らさず docs/design・ADR・memory へ**リンク**する (B が D を参照する形):
  ```markdown
  # <タスク名>

  - ID: <TASK_ID>
  - ブランチ: <ブランチ名>
  - ベース: <ベースブランチ>
  - Linear: <ELM-123 or ->
  - 作成: <ISO8601>

  ## 目的 / タスク
  <親セッションで着手しようとしていた内容>

  ## 方針 / 制約
  <設計方針・決定事項。詳細は下の「関連」のリンク先 (docs/design・ADR・memory) を参照>

  ## 受け入れ基準
  - [ ] <...>

  ## 関連
  - docs/design/<...>.md / docs/adr/<...>.md
  - Linear: <URL or ->
  - 親の決定 (memory): <該当があれば要点を 1-2 行で>
  ```
- 引き継ぐ具体タスクが未確定なら、最低限「目的」にタスク説明文を入れて雛形だけ作る (子はこれを起点に親へ確認できる)

### 5. タスクレジストリに登録
- レジストリファイル: `${GIT_COMMON_DIR}/parallel-tasks.json`
- 既存ファイルがなければ `{"tasks":[]}` で初期化
- 以下のエントリを追加:
  ```json
  {
    "name": "<タスク名>",
    "branch": "<ブランチ名>",
    "worktree_path": "<worktreeのフルパス>",
    "base_branch": "<ベースブランチ>",
    "description": "<タスクの説明>",
    "started_at": "<ISO8601>",
    "status": "active",
    "linear_issue_id": "<ELM-123 or null>",
    "linear_issue_url": "<URL or null>",
    "task_id": "<TASK_ID>",
    "task_doc": "<TASK_DOC のフルパス>"
  }
  ```
- jq がインストールされていない場合は Python の json モジュールで代替する

### 6. zellij 別タブで着手 (`--tab` 指定時のみ)

`--tab` が指定され、かつ zellij セッション内 (`$ZELLIJ` が設定されている) なら、worktree を cwd にした新しい zellij タブを開き、worktree へ `cd` してから、**引き継ぎドキュメント (手順4) を初期プロンプトに渡して** `claude` を自動起動する (Enter まで送る)。`--no-remote` 時は `--remote-control` を省く。

```bash
PROMPT="${TASK_DOC} を読んで、記載のタスクに着手してください"
if [ -n "${ZELLIJ:-}" ]; then
  zellij action new-tab --cwd "<worktree パス>" --name "<タスク名>"   # 新タブを開く
  zellij action go-to-tab-name "<タスク名>"                            # フォーカスを新タブに確定 (注入先を保証)
  # worktree へ明示 cd → 引き継ぎドキュメントを初期プロンプトに渡して claude 起動。
  # --remote-control は = で名前を束縛し、位置引数をプロンプトにする (両立のため)。--no-remote 時は: claude "$PROMPT"
  zellij action write-chars "cd \"<worktree パス>\" && claude --remote-control=\"<タスク名>\" \"$PROMPT\""
  zellij action write 13                                              # Enter(CR) を送って自動起動
else
  echo "warning: zellij セッション外のため --tab は無視。手動で起動してください。"
fi
```

- 子は起動と同時に引き継ぎドキュメントを読み、親の意図・方針を引き継いで着手する (B+D)
- `write 13` が Enter。`new-tab` 直後でもシェルは pty バッファ経由で入力を受けるため、実使用では確実に実行される
- タブ名 = タスク名になるため、`/worktree-list` と併せて「どのタブが何の作業か」が一目で分かる
- 引き継ぎ起動したくない (素の claude で開きたい) 場合は初期プロンプトを外す
- 別 zellij セッション (`claude --remote-control` を別端末で) より軽い「真の並列」着手手段

### 7. ユーザーへの案内
以下を表示する (Linear 連携時は Issue 情報も含める)。`--tab` 指定時は「別タブを開いて worktree に cd し、引き継ぎドキュメントを渡して `claude` を自動起動した」と案内する。`--tab` 無し (手動起動) の場合は、起動後に引き継ぎドキュメントを読ませる起動コマンドを案内する。`--no-remote` 時は `--remote-control ...` を省く。

```
worktree を作成しました:
  パス:        <worktree パス>
  ブランチ:    <ブランチ名>
  引き継ぎ doc: <TASK_DOC のフルパス>
  Linear:      <ELM-123 In Progress に遷移>  ← --linear 指定時のみ
               <Issue URL>

新しい Claude Code セッションを以下で起動してください (--tab 指定時は別タブで自動起動済み):
  cd <worktree パス> && claude --remote-control="<タスク名>" "<TASK_DOC> を読んで着手して"
  (--no-remote 指定時は `claude "<TASK_DOC> を読んで着手して"`)

(iPhone 公式 Claude アプリの Code タブから push 通知・接続切替が可能。Pro プラン以上必須)

他のタスクの状況は /worktree-list で確認できます。
完了後は /worktree-finish でマージしてください (引き継ぎ doc は削除されません)。
```

## 注意事項
- タスク引き継ぎドキュメントは `<共有.git>/worktree-tasks/` に永続保存し、`/worktree-finish` でも削除しない (タスクの記録として残す)。git 管理外なのでリポは汚さない
- 同名のタスクが既に active の場合はエラーにする
- worktree ディレクトリの親が存在しない場合は作成する
- ベースブランチの最新コミットから分岐する
- `--linear` 指定時に Linear MCP が未認証なら、Issue 連携部分だけ skip して警告を出し、worktree 作成自体は継続する (`linear_issue_id` のみレジストリに記録)
- Linear ID は大文字小文字を区別しない (`elm-123` / `ELM-123` どちらでも受け付け、ブランチ名は lowercase に統一)
