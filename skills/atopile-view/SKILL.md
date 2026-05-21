---
name: atopile-view
description: atopile プロジェクトの回路を確認する。BOM・接続済みピン・接続ツリーをサマリ表示し、KiCad pcbnew や PDF エクスポートなど次のアクションを案内する。実験フォルダで「回路を見たい」「pcbnew を開きたい」「BOM を確認したい」「接続を確認したい」ときに使用
argument-hint: [<experiment-name|path>] [--target <build>] [--bom | --pinout | --tree | --kicad | --pdf [<file>] | --inspect <component>]
disable-model-invocation: false
allowed-tools: Bash(ato *) Bash(pcbnew *) Bash(kicad-cli *) Bash(cat *) Bash(ls *) Bash(jq *) Bash(python3 *) Bash(awk *) Bash(find *) Bash(test *) Bash(which *) Bash(git *) Bash(uv *) Bash(column *) Bash(head *) Bash(pgrep *) Bash(xdg-open *) Read Write
---

# atopile プロジェクト確認

atopile の `.ato` から生成されたビルド成果物を確認し、回路を視覚 / テキストで把握する。
任意の atopile プロジェクト (`ato.yaml` を持つディレクトリ) で動作する汎用 skill。

## プロジェクト特定の解決順

1. 第 1 引数が **絶対パスまたは相対パス**で `ato.yaml` を含むディレクトリ → そこを使う
2. 第 1 引数が**名前 (kebab-case)** で、カレント or 親に `experiments/<name>/ato.yaml` がある → そこを使う (tamayori-lab パターン)
3. 引数なし → カレントディレクトリから親方向に `ato.yaml` を探索 (`git rev-parse --show-toplevel` まで)
4. 見つからなければエラー: 「ato.yaml が見つからない。プロジェクトディレクトリで実行するか、パスを引数で指定してください」

## Build target の解決

`<target>` の決定順 (依存追加なしで動かす):

1. **`--target <name>` 指定があればそれを使う**
2. **既ビルドがあれば `build/builds/` のサブディレクトリ名から取得**
   ```bash
   ls -1 build/builds 2>/dev/null
   ```
3. **未ビルドなら ato.yaml を awk で軽くパース** (PyYAML には依存しない)
   ```bash
   awk '/^builds:[[:space:]]*$/{flag=1;next}
        flag && /^[^[:space:]]/ {exit}
        flag && /^[[:space:]]+[A-Za-z_][A-Za-z0-9_-]*:[[:space:]]*$/{
          gsub(/^[[:space:]]+|:[[:space:]]*$/,""); print
        }' ato.yaml
   ```
4. 候補が 1 つだけならそれを採用。複数あれば一覧表示してユーザーに選択させる。
5. 以降、成果物パスは `build/builds/<target>/...` と `layouts/<target>/<target>.kicad_pcb` を参照 (atopile はビルド名と同じ basename でファイルを置く)。

awk パースが想定外の YAML 構文で動かないときは「`ato build` を 1 回走らせてから再実行してください」を案内する (ビルド後は手順 2 で確実に取得できる)。

## 前提

- `ato` CLI が PATH にある (`which ato`)。無ければ案内: atopile 0.15.x は Python 3.14 を要求するので `uv tool install --python 3.14 atopile` (uv が Python 3.14 を自動取得するため事前準備は不要)。uv 自体が無ければ https://docs.astral.sh/uv/getting-started/installation/ を案内
- KiCad 10 がインストールされている (`pcbnew` / `kicad-cli` コマンド)。無ければ GUI 操作 (`--kicad` / `--pdf`) はスキップし、テキストモードのみで完結する

## ビルド状態の確認

選択した `<target>` について以下を確認し、足りなければ `ato build` を実行する:

- `build/builds/<target>/<target>.bom.csv` の有無
- `layouts/<target>/<target>.kicad_pcb` の有無
- ソース (`*.ato`) の mtime > `build/builds/<target>/` の mtime ならビルド再実行

`ato build` の出力は最後の Build Summary 部分だけを表示する。
失敗時はエラー全文を表示して中断する。

## サブコマンド (引数なし: デフォルトサマリ)

### デフォルト (`--summary` 相当)

1. プロジェクト名・選択 build target・ato 本体バージョンを表示
2. **BOM サマリ**: 部品種別ごとの数 + 主要部品 (MCU / コネクタ / IC) のリスト (上位 10 行 + `(... N items)`)
3. **接続済みピン サマリ**: 各 IC ピン JSON (`build/builds/<target>/pinout/*.json`) を読み、`isConnected: true` のピンを `{designator, lead, net}` 形式で 1 IC ずつまとめる
4. **アクション提示**: 以下を 1 画面で案内
   - `pcbnew layouts/<target>/<target>.kicad_pcb &` (KiCad PCB ビュー)
   - `kicad-cli pcb export pdf -o board.pdf layouts/<target>/<target>.kicad_pcb` (PDF)
   - `ato inspect <component>` (個別深掘り)

### `--bom`

`build/builds/<target>/<target>.bom.csv` を `column -t -s,` で整形して表示する。
30 行以上の場合は `head -30` で切り、末尾に `(... N more)` を添える。

### `--pinout`

`build/builds/<target>/pinout/*.json` を全て読み、`isConnected: true` のピンを designator 別に集約して表示する。
出力形式: `<Designator> (<ato-address>)` をヘッダにし、配下に `<lead>: net=<netName>` の 1 行ずつ。

### `--tree`

`build/builds/<target>/<target>.data_interface_tree.ato.json` から **Mermaid graph** を生成して標準出力に書く。
- 各 interface (USB2_0, ElectricPower 等) を `subgraph` ブロック
- ノードラベルに `groupLabel` (例: `Esp32Blink.mcu`) を使う

### `--kicad`

`pcbnew layouts/<target>/<target>.kicad_pcb &` をバックグラウンド起動。
プロセス起動の確認 (`pgrep -f pcbnew`) だけ行い、ユーザーに GUI で確認するよう案内する。

### `--pdf [<file>]`

`kicad-cli pcb export pdf -o <file> layouts/<target>/<target>.kicad_pcb` でレイヤごとの PDF を出力。
デフォルト出力先は `build/builds/<target>/<target>.pdf`。
最後にファイルパスを表示し、`xdg-open <file>` の提案を添える。

### `--inspect <component>`

`ato inspect <component>` を実行してその結果を表示する。
`<component>` は `.ato` ソースのアドレス (例: `Esp32Blink.mcu`)。

## 出力ガイドライン

- 各セクション 10 行以内を目安に
- BOM が長い場合は `head -30` で切って `(... N items, see --bom for full list)` を添える
- 失敗時は最後にハマりどころのヒントを 1 行 (例: 「ato が古いと build が通らない: `uv tool install --force --python 3.14 atopile` で最新化」)

## 注意事項

- `build/` / `parts/` / `.ato/` は atopile が自動再生成可能で、git 管理外を前提に動く
- KiCad が無いホスト (CI / SSH リモート) では `--bom` / `--pinout` / `--tree` のみで完結する
- 同名の experiments が複数階層に存在するケースでは曖昧さを警告しユーザに確認する
- atopile 0.15.x は Python 3.14 を厳密に要求する。`uv tool install atopile` を `--python` なしで叩くと旧 0.2.x が入るので必ず `--python 3.14` を渡す (uv が事前ビルド済 Python 3.14 を自動取得するためホストに Python 3.14 が無くても OK)
