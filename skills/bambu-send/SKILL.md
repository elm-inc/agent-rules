---
name: bambu-send
description: Bambu Lab プリンタ (A1 mini / X2D / H2D 等) へ LAN 経由でスライス済み 3mf を送り、印刷を開始する。FTPS(990) + MQTT(8883) の直送でクラウドを経由しない。プリンタにファイルを送りたい・印刷を始めたい・プリンタの状態やファイル一覧を見たいときに使用
argument-hint: "<subcommand> | init | discover | doctor | status | ls [path] | upload <file.3mf> | print <file.3mf> [--plate N] --yes"
disable-model-invocation: false
allowed-tools: Bash(python3 ~/repos/github.com/elm-inc/agent-rules/skills/bambu-send/scripts/bambu_send.py*) Bash(python3 ~/.claude/skills/bambu-send/scripts/bambu_send.py*) Bash(cat *) Bash(ls *) Bash(test *) Read
---

# Bambu プリンタへの LAN 直送

スライス済みの `.3mf` をプリンタの SD カードへ置き、印刷を開始する。クラウド
(Bambu のサーバ) を経由しないので、プリンタがアカウントに紐付いていなくても動く。

```bash
SKILL=~/.claude/skills/bambu-send/scripts/bambu_send.py

python3 $SKILL init                      # 設定の雛形 (~/.config/agent-rules/bambu.toml)
python3 $SKILL discover                  # LAN の Bambu 機を探す (host / serial が分かる)
python3 $SKILL doctor                    # 経路ごとに疎通を確かめる
python3 $SKILL status                    # 状態を 1 回読む
python3 $SKILL ls /cache                 # プリンタ上のファイル一覧
python3 $SKILL upload part.3mf           # 置くだけ (印刷しない)
python3 $SKILL print part.3mf --yes      # 置いて印刷を始める
```

## 使うときの流れ

1. **`discover`** で `host` と `serial` (USN) を得る
2. **`init`** で `~/.config/agent-rules/bambu.toml` を作り、`host` / `serial` /
   `access_code` を埋める。アクセスコードは**プリンタ画面 → 設定 → ネットワーク**
3. **`doctor`** で FTPS と MQTT の両方が通ることを確かめる
4. 送る。**まず `upload` で置けることを確かめ**、良ければ `print --yes`

## 安全の線 (なぜこう作ってあるか)

- **`print` は `--yes` が要る。** 印刷はフィラメントと時間を消費する戻せない操作なので、
  既定では「何をしようとしているか」を表示して終了コード 2 で止まる
- **実行中のジョブを潰さない。** `gcode_state` が IDLE / FINISH / FAILED でなければ中止する
- **送る前に 3mf の中身を検査する。** 指定プレートの g-code が無ければ**送らない**。
  md5 が入っていれば突き合わせる (壊れたものを送らない)
- **アクセスコードを argv に出さない。** 設定ファイル (600) か環境変数からのみ読む。
  `ps` に出る形では受け取らない
- **削除しない。** プリンタ上のファイルを消すサブコマンドを持たない
  (利用者の `*.gcode` を消す事故を構造的に防ぐ)
- **常駐しない。** MQTT は用事のたびに繋いで閉じる。開始を見届ける時間だけ待ち、
  確認できなければ**成功と言わずに** 終了コード 1 で返す
- **依存を足さない。** 標準ライブラリだけで動く (MQTT 3.1.1 を手で喋る)。
  呼び出し元プロジェクトの依存を汚さないため

## 設定

`~/.config/agent-rules/bambu.toml` (**この repo には置かない** — public なので):

```toml
default = "a1mini"

[printer.a1mini]
host = "192.168.0.1"
serial = "00M00A000000000"
access_code = "00000000"
# bed_type = "textured_plate"
```

環境変数 `BAMBU_HOST` / `BAMBU_SERIAL` / `BAMBU_ACCESS_CODE` が全部あればそちらが優先される
(CI や一時的な別機向け)。

## 送れるもの・送れないもの

**スライス済みの `.3mf` だけ**が印刷できる。形状だけの STL / STEP / 3mf は
`Metadata/plate_N.gcode` を持たないので、検査で弾かれる。作り方は
[`reference/slicing.md`](reference/slicing.md)。

`upload` は任意のファイルを置ける (印刷はしない)。

## 終了コード

| コード | 意味 |
|---|---|
| 0 | 成功 |
| 1 | エラー / 開始が確認できなかった |
| 2 | `print` を `--yes` なしで呼んだ (何もしていない) |

## 他のツールとの関係

- **ai-cad は使わない**。ai-cad はプリンタジョブを持たない設計 (ADR-0008 が
  「決して持たないもの」にプリンタジョブ管理を挙げ、`tests/test_architecture.py` が
  機械検証している) ので、送信はこのスキルの側にある
- **`/cad-print`** は形を作る側。ここは出来た形を機械に渡す側
