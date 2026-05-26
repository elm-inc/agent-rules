---
name: rigol-dho804
description: RIGOL DHO804 オシロスコープから LAN (VXI-11/LXI) 経由でスクリーンショット・波形・計測値・設定を取得する。波形を CSV で取りたい、画面を保存したい、Vpp/周波数を読みたいときに使用
argument-hint: "<subcommand> [options] | info | screenshot | waveform | measure | setup"
disable-model-invocation: false
allowed-tools: Bash(uv *) Bash(ls *) Bash(cat *) Bash(mkdir *) Bash(test *) Read Write
---

# RIGOL DHO804 データ取得

LAN 接続された RIGOL DHO804 から VXI-11 (LXI 標準) で SCPI コマンドを送り、波形・スクリーンショット・計測値・設定をローカルに保存する。

## 接続経路

- **プロトコル**: VXI-11 (TCP/IP) — `pyvisa` + `pyvisa-py` バックエンド
- **VISA リソース文字列**: `TCPIP::<host>::INSTR`
- 本体は LAN ポートで DHCP / 固定 IP のいずれでも可。Web UI (`http://<host>/`) から IP を確認できる

## 接続先の解決順

1. `--host <ip>` (コマンドライン引数)
2. 環境変数 `RIGOL_DHO804_HOST`
3. `~/.config/rigol-dho804.toml` の `host = "<ip>"`

いずれも未設定ならエラーで終了する。

### 設定ファイルの例

`~/.config/rigol-dho804.toml`:

```toml
host = "192.168.1.50"
# 任意: timeout = 10000          # ms (デフォルト 10000)
```

## 実行スクリプト

`scripts/rigol_dho804.py` は PEP 723 inline metadata で依存を宣言した self-contained な uv スクリプト。グローバルな pip install 不要。

このスキルが Claude Code から呼ばれた場合、スキルのベースディレクトリ (`${SKILL_DIR}`) が `<subcommand>` の実行時に渡されている。`uv run` には絶対パスでスクリプトを指定する:

```bash
uv run ${SKILL_DIR}/scripts/rigol_dho804.py <subcommand> [options]
```

手動で叩く場合は agent-rules リポ配下の `skills/rigol-dho804/scripts/rigol_dho804.py`、または `install.sh` 実行後の symlink 経由 `~/.claude/skills/rigol-dho804/scripts/rigol_dho804.py` を指定する。

初回実行時に uv が `pyvisa` / `pyvisa-py` を ephemeral 環境に取得する。

## サブコマンド

### `info`
`*IDN?` とエラーキューを表示する。接続確認に使う。

```bash
uv run ${SKILL_DIR}/scripts/rigol_dho804.py info
```

### `screenshot`
現在の画面を PNG で保存。`:DISP:DATA? PNG` で IEEE 488.2 binary block を取得。

```bash
uv run ${SKILL_DIR}/scripts/rigol_dho804.py screenshot
uv run ${SKILL_DIR}/scripts/rigol_dho804.py screenshot -o capture.png
```

デフォルトファイル名: `dho804_screen_YYYYMMDD_HHMMSS.png`

### `waveform`
チャンネル波形を CSV (`time_s,volt_v`) で保存。

| オプション | 説明 |
|---|---|
| `-c <1-4>` | チャンネル番号 (デフォルト 1) |
| `-m normal\|raw\|maximum` | `normal`=画面表示分のみ、`raw`=メモリ全体 (実行前に `:STOP` する)、`maximum`=自動 |
| `-f ascii\|byte\|word` | 転送フォーマット。`byte`/`word` は IEEE 488.2 バイナリで高速、`ascii` は CSV テキスト |
| `-n <points>` | 取得ポイント数の上限 |
| `-o <path>` | 出力 CSV パス |

```bash
# 画面表示分を CH1 から取得
uv run ${SKILL_DIR}/scripts/rigol_dho804.py waveform -c 1

# メモリ全体 (RAW) を CH2 から取得し binary 転送 (高速)
uv run ${SKILL_DIR}/scripts/rigol_dho804.py waveform -c 2 -m raw -f byte
```

転送が `byte`/`word` の場合、preamble (`:WAVeform:PREamble?`) のスケールで電圧に変換してから CSV 化する。`raw` モードは内部メモリ全体 (最大 50 Mpts 程度) を 250000 点ずつチャンクして読む。

### `measure`
`:MEASure:ITEM? <item>,<channel>` で計測値を取得する。複数項目を一度に指定可能。

```bash
uv run ${SKILL_DIR}/scripts/rigol_dho804.py measure VPP FREQ -c 1
uv run ${SKILL_DIR}/scripts/rigol_dho804.py measure VRMS VMAX VMIN PERiod -c 2
```

主な項目: `VPP`, `VMAX`, `VMIN`, `VAVG`, `VRMS`, `VTOP`, `VBASe`, `VAMP`, `FREQuency`, `PERiod`, `RTIMe`, `FTIMe`, `PWIDth`, `NWIDth`, `PDUTy`, `NDUTy`, `OVERshoot`, `PREShoot`。

戻り値が `9.9e37` 付近の場合は計測不能 (波形が無いなど) として `(invalid / not measurable)` と表示する。

### `setup`
現在のスコープ設定を保存する。

- **デフォルト (テキスト要約)**: タイムベース、トリガ、各チャンネルの主要 SCPI クエリ結果を `.txt` で保存。diff で設定差分を比較できる
- `--binary`: `:SYSTem:SETup?` で内部設定のオパーク binary block を `.stp` に保存。本体に書き戻すと完全に状態を再現できる (本体の `:SYSTem:SETup #...` で復元)

```bash
uv run ${SKILL_DIR}/scripts/rigol_dho804.py setup            # text summary
uv run ${SKILL_DIR}/scripts/rigol_dho804.py setup --binary   # 完全な再現可能スナップショット
```

## 引数の解釈

`$ARGUMENTS` を以下の流れで解釈する:

1. 先頭トークンがサブコマンド (`info` / `screenshot` / `waveform` / `measure` / `setup`) であることを確認
2. 残りを Python 側の argparse にそのまま渡す
3. サブコマンドが省略された場合はユーザーに用途を確認する (画面保存? 波形取得?)

## 実行手順

1. 設定ファイル `~/.config/rigol-dho804.toml` または `--host` で接続先を確認
2. まず `info` で `*IDN?` を表示し、応答があることを確認する
3. ユーザーの要求に応じたサブコマンドを実行
4. 保存したファイルのパスとサイズを報告

## 注意事項

- 本体は LXI に準拠しており Web UI (`http://<host>/`) からも IP・GPIB アドレスを確認できる
- `pyvisa-py` の VXI-11 実装は VISA-NI と異なり遅延が大きい。`raw` モードでメモリ全体を読むと数秒〜十数秒かかる
- `raw` モード取得時はスクリプトが自動で `:STOP` を送る。継続取得が必要なら手動で `:RUN` を送るか本体の Run キーで再開する
- 同じネットワークセグメントから到達できない場合は `pyvisa.errors.VI_ERROR_TMO` (タイムアウト) になる。`--timeout` を増やすか、ping で疎通を確認する
- 設定ファイルに `host` をハードコードする場合、ホスト名 (`dho804.local` 等 mDNS) も使える。DHCP 環境ならホスト名指定が安定する
