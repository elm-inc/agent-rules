---
name: ports
description: 複数案件のポート利用状況を調べる。いま何番をどの案件が使っているか、停止中の案件が何番を使う設定か、空きはどこか、なぜ起動できないかを答える。「あの案件のポート何番だっけ」「ポートが衝突して立ち上がらない」ときに使用
argument-hint: "[案件名 | free [--block N] | check [案件名] | all]"
disable-model-invocation: false
allowed-tools: Bash(python3 /home/elmo/repos/github.com/elm-inc/agent-rules/scripts/port-inventory.py*) Read
---

# ポート利用状況の棚卸し

複数案件を 1 台で並行開発していると「どの案件がどのポートか」が分からなくなる。実態 (docker ラベル・`/proc`) と設定 (compose/vite/.env) を突き合わせて、ポートに案件名を付ける。

根拠と設計判断: [`docs/adr/0018`](../../docs/adr/0018-port-inventory-and-registry.md)

## 前提

- エンジン: `~/repos/github.com/elm-inc/agent-rules/scripts/port-inventory.py` (依存は PyYAML のみ)
- 予約台帳 `~/.config/agent-rules/ports.yml` は **任意**。無くても全機能が動く
- **台帳は agent-rules に置かない** — public repo なので案件名が公開される (ADR-0018)

## 引数の解釈

`$ARGUMENTS` を以下のルールで解釈する:

1. **引数なし** → `list`: いま LISTEN しているポートを案件名付きで一覧
2. **`all`** → `list --all`: 案件を特定できないもの (システム・他ユーザ) も含めて表示
3. **`free`** (+ `--block N`) → 空きポート / N 連続の空き帯を提案
4. **`check`** (+ 任意で案件名) → いま起動できない案件を検出。案件名を渡すとその案件だけ詳細に
5. **`init`** → 予約台帳の雛形を作る
6. **その他のテキスト** → 案件名とみなして `project` で引く (部分一致・停止中でも設定から引ける)

## 実行手順

```bash
SCRIPT=~/repos/github.com/elm-inc/agent-rules/scripts/port-inventory.py

# 1. 一覧 (引数なし)
python3 "$SCRIPT" list

# 2. 案件で引く (停止中でも設定から引ける)
python3 "$SCRIPT" project <案件名>

# 3. 空き探し
python3 "$SCRIPT" free                # 空きポートを 5 個
python3 "$SCRIPT" free --block 100    # 100 連続の空き帯

# 4. 衝突検出 (案件名を渡すと exit 1 で fail-close)
python3 "$SCRIPT" check
python3 "$SCRIPT" check <案件名>

# 5. 台帳の雛形
python3 "$SCRIPT" --registry-init
```

## 結果の読み方

| 列 | 意味 |
|---|---|
| 種別 `docker` | compose ラベルから repo を確定 |
| 種別 `proc` | `/proc/<pid>/cwd` から git root を確定 |
| 案件名の末尾 `~` | **推測** (compose ラベルの無い `docker run` 由来。コンテナ名から repo 名を推測した) |
| `※削除済み worktree で稼働中` | worktree は消えたのにプロセスが残っている = 掃除し忘れ |

`ss` でプロセス名が取れるのは自分が所有するものだけで、docker 公開ポートは root 所有の `docker-proxy` になる。既定では**案件が特定できたものだけ**を表示し、残りは件数のみ示す (`all` で全件)。

## 衝突検出の考え方

**「複数案件が同じポートを宣言している」は同時に起動しなければ無害**なので警告しない。実際に手が止まるのは「起動しようとした案件が、既に埋まっているポートを要求する」ときだけ。

- `.env` の `*PORT=` は多くが**接続先**であって確保ではない (`DB_PORT=5432` は docker ネットワーク内を指すだけ) ため、衝突判定には使わない
- 判定に使うのは compose の `ports:` ホスト側・vite の `server.port`・`--port` だけ

**exit code (fail-close)**: `check` は ERROR があれば 1。加えて **`docker` や `ss` が使えず live を調べられなかった場合も 1** を返す。「調べられなかった」を「問題なし」と取り違えないため (欠落理由は WARN で stderr に出る)。

## コマンド例

```bash
# いま何が動いている?
/ports

# あの案件のポート何番だっけ (停止中でも分かる)
/ports example-app

# 新しい案件に 100 ポートの帯を切りたい
/ports free --block 100

# 起動しようとしたら失敗した — 何とぶつかっている?
/ports check example-app
```

## 台帳 (任意)

`~/.config/agent-rules/ports.yml` に案件ごとの帯を宣言すると、`check` が「帯の重複」「帯からの逸脱」「未登録の占有」を検出する。

```yaml
version: 1
projects:
  # 連続した帯で確保する場合
  example-app:
    repo: ~/repos/github.com/example-org/example-app
    range: [13000, 13099]
    note: "13000=frontend 13001=admin 13010=api"

  # 慣用ポート (web=3000 / db=5432) で帯にまとまらない案件はポート列で書く
  legacy-app:
    ports: [3000, 5432, 6379]
```

**帯だけでなくポート列も受ける**理由: 実測すると多くの案件は「web=3000 / db=5432」の慣用ポートを使っており、連続帯にまとまらない。`range` しか書けない台帳はそういう案件で使えない。`range` と `ports` は併用できる (どちらも確保として扱う)。

## 変更するときは

解析ロジック (compose の port 表記・台帳 YAML・行の畳み込み) は **壊れても実行時エラーにならず「衝突なし」と静かに嘘をつく**。変更したら回帰テストを通すこと。CI (`port-inventory-test.yml`) でも走る。

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/scripts/test-port-inventory.py
```

## 注意事項

- **台帳を agent-rules にコミットしない**。案件名を含むため public repo に載せてはいけない (ADR-0018)
- 設定スキャンは best-effort。動的にポートを決めるアプリは宣言側に出てこない (live 側では捕捉される)
- 案件名の末尾 `~` は推測。確定させたいなら compose 経由で起動する (ラベルが付く)
- ポートを空けるために**プロセスを勝手に kill しない**。何が動いているかを示すところまでが本スキルの役割
