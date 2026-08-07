---
name: mosh-clean
description: このホストに残存した mosh-server セッションを一覧し、不要なものを手動で安全に終了する。「mosh のセッションが残っている/溜まっている」「古い mosh を消したい」「mosh-server が大量に動いている」ときに使用。今使っているセッションは自動で保護する
argument-hint: "[list] | kill <PID> [<PID> ...] [--force]"
disable-model-invocation: true
allowed-tools: Bash(python3 ~/repos/github.com/elm-inc/agent-rules/skills/mosh-clean/scripts/mosh_clean.py*) Bash(ps *) Bash(who *) Bash(ss *) Read
---

# /mosh-clean — 残存 mosh セッションの手動クリーンアップ

mosh-server は**クライアントの回線が切れても終了せず再接続を待ち続ける**。ノート PC を閉じる・
回線が変わる・別マシンから繋ぎ直す、を繰り返すと「もう誰も使っていない」mosh-server がホスト上に
溜まる。このスキルはそれを一覧し、**人間が選んだものだけを安全に終了**する。

- **対象はこのホスト上の mosh-server プロセス**（ローカル）。リモート先のセッションは対象外。
- **自動 kill はしない**。idle・接続元・中身を提示して、終了する PID は人間が指定する。
- 危険な kill はガード付きスクリプト内に閉じ込めてある（後述の安全装置）。

## スクリプト

`scripts/mosh_clean.py` は stdlib のみの self-contained スクリプト（外部依存なし、Linux 専用）。
情報源は `/proc` ・`who -u` ・`ss`。canonical path で起動する:

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/skills/mosh-clean/scripts/mosh_clean.py <subcommand>
```

（`install.sh` 後は symlink `~/.claude/skills/mosh-clean/scripts/mosh_clean.py` でも可）

## サブコマンド

### `list`（既定）

全 mosh-server を一覧する。各行に PID / UDP ポート / 接続元 IP / ログイン時刻 / **idle** /
**中で動いているもの**（素の bash か、zellij/tmux か、実行中コマンドか）を表示し、
**いま自分が使っているセッション (current)** を検出して `← CURRENT` で印を付ける。

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/skills/mosh-clean/scripts/mosh_clean.py list
```

idle が長い順（=残存の疑いが濃い順）に並ぶ。

### `kill <PID> [<PID> ...]`

指定した mosh-server を SIGTERM で終了する（落ちなければ自動で SIGKILL に昇格）。

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/skills/mosh-clean/scripts/mosh_clean.py kill 1633893 1655012
```

| オプション | 意味 |
|---|---|
| `--force` | current（今使っている）セッションでも強制終了する |
| `--dry-run` | 実際には送らず、何を kill する予定かだけ表示 |

## 安全装置（スクリプト内蔵）

1. **mosh-server 以外の PID は kill 拒否**。`mosh-server` を含まないコマンドの PID を渡しても何もしない。
2. **current セッションは `--force` なしでは kill 拒否**。`/mosh-clean` 実行中の自分の足元を切らない。
3. SIGTERM → 最大 ~2 秒待って残っていれば SIGKILL、という順で結果を逐一報告する。

> current 検出は zellij/tmux 越しでも効く（multiplexer サーバは init に reparent されるため、
> アタッチ中クライアントの制御端末 pts → mosh-server を逆引きして特定する）。万一 current を
> 「不明」と表示したときは、kill 対象の `source` / `idle` を必ず目視確認してから消すこと。

## 実行手順（このスキルが呼ばれたとき）

1. まず `list` を実行し、表をユーザーに見せる。
2. **どれを終了するかはユーザーに確認する**（手動が原則）。`← CURRENT` の行は提案しない。
   - 「残存の疑いが濃い」候補の目安: idle が長い／中身が素の bash／古いログイン。ただし
     idle はあくまでランク付けの材料で「使っていない」証明ではない（放置中の長時間ジョブ等もある）。
   - 「全部消したい（current 以外）」と言われたら、CURRENT を除く PID をまとめて `kill` に渡す。
3. ユーザーが選んだ PID を `kill <PID> ...` で終了し、結果を報告する。
4. current を消したい明示の要望があるときのみ `--force` を付ける（消すと自分の mosh 接続が切れる旨を先に伝える）。

## 注意

- 別ユーザーの mosh-server は権限で kill できない（その場合は報告のみ）。
- `ss` / `who` が情報を返さない環境ではポートや接続元が `?` になることがあるが、列挙と kill は機能する。
- リモートホスト上の残存セッションを掃除したい場合は、そのホストにログインしてからこのスキルを使う
  （本スキルはローカル `/proc` を見るため SSH 越し操作はしない）。
