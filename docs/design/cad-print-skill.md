# 設計: `/cad-print` — build123d × 3D プリンタ造形の媒介スキル

- ステータス: ドラフト(レビュー前)。決定の根拠は [ADR-0007](../adr/0007-build123d-3d-printing-cad-skill.md)
- 関連: [ADR-0005](../adr/0005-on-demand-local-llm.md)(オンデマンド env)

## 1. 目的 / 非目的

**目的**: Claude Code で build123d を使い、3D プリンタ向けの造形を「**書く→診断→視認→調整**」の反復で安定して進める。横断知識(規約・嵌合較正・視覚ループ・環境)を skill に集約し、各プロジェクトは造形指示に集中する。

**非目的(現スコープ外)**: スライサ自動化(G-code 生成)、プリンタへの送信、トポロジ最適化/FEA、GUI。3MF + プロファイル受け渡しは次段。

## 2. 役割分担

| レイヤ | 持ち物 |
|---|---|
| **プロジェクト(毎回)** | 造形指示・寸法・制約。成果物 `part.py`(build123d)+ `model.toml`(パラメータ + 対象プリンタ/素材) |
| **`/cad-print`(媒介・agent-rules)** | ① build123d 規約注入 ② 較正値テーブル + `fit()` ③ **診断(干渉/クリアランス/肉厚/オーバーハング)自前** ④ 反復ループ統括 ⑤ シェーディング描画 ⑥ env bootstrap |
| **cad-khana(外部依存・vendored+pin・optional)** | **`khana draw`(HLR 正投影/等角 線画)中心**。Assembly/joint/animation は任意。不在でも skill は degradable に動く |

## 3. アーキテクチャと反復ループ

```
[造形指示] ── Claude が part.py を規約準拠で記述/修正 (fit() で較正値参照)
                       │
            /cad-print build part.py
                       │
   ┌───────────────────┼─────────────────────────────┐
   │ env-ensure        │ 診断 (skill 自前)    │ 描画 (skill + khana)        │
   │ uv venv 構築/確認  │ 干渉/クリアランス/    │ shaded iso/front/top (pyrender)│
   │ (build123d/OCP/    │ 肉厚/オーバーハング  │ + khana draw 線画 (GL 不要)     │
   │  trimesh/+khana)   │ → diagnostics.json  │   (GL 全滅時は線画のみで継続)   │
   └───────────────────┴─────────────────────┴──────────────────────────────┘
                       │
      Claude が ① diagnostics.json (pass/fail+実測値) を読む
               ② PNG を“見る”(形の妥当性をマルチモーダル判断)
                       │
            fail or 見た目が違う → パラメータ/形状を調整して再ループ
            pass かつ妥当       → /cad-print export → STEP / STL / 3MF
```

## 4. スキル構成(agent-rules)

```
skills/cad-print/
  SKILL.md                      # ルーティング + 使い方 + 規約への導線
  reference/
    build123d-conventions.md    # 規約チートシート (context 注入)
    fit-calibration.md          # 較正の考え方・ガウジ運用
  scripts/
    cad_print.py                # CLI 本体 (PEP723 uv, サブコマンド)。part.py は subprocess+timeout で実行
    ensure_cad_env.py           # 専用 venv のオンデマンド構築 (ADR-0005 方式)。全依存 pin + GL/OS lib 検査
    diagnostics.py              # 自前診断: 干渉/クリアランス/肉厚(voxel)/オーバーハング → 正規化 diagnostics.json
    render_shaded.py            # trimesh+pyrender オフスクリーン (EGL→OSMesa→xvfb→線画フォールバック)
    khana_draw.py               # vendored cad-khana の HLR 線画呼び出し (optional, pin)
    fits.py                     # fit()/hole()/peg()/gap() — モデルが import (符号・適用先・軸を明示)
  templates/
    part.py.tmpl                # 規約準拠の雛形
    model.toml.tmpl             # パラメータ + プリンタ/素材
    calibration.toml            # 既定較正値 (seed) + ユーザー上書き
```
`install.sh` が `skills/*/` を自動 symlink。専用 venv は `~/.cache/cad-print/venv`(リポ外)。

## 5. サブコマンド

| コマンド | 役割 |
|---|---|
| `init [dir]` | プロジェクト雛形展開(part.py / model.toml / outputs/) |
| `build <script>` | env-ensure → khana check → shaded+線画 render → 診断+画像パス要約(**主ループ**) |
| `check <script>` | 診断のみ(高速・描画なし) |
| `render <script> [--views iso,front,top] [--shaded/--line]` | 描画のみ |
| `fit list\|get <type>\|set <type> <mm>` | 較正値の参照/更新(対象プリンタは model.toml or `--printer/--material`) |
| `calib gauge [--range ...]` | クリアランス試験ガウジ STL を生成(実機較正用) |
| `calib set <type> <mm>` | 実測結果を calibration.toml に記録 |
| `export <script> --format step\|stl\|3mf` | 最終出力 |
| `conventions` | 規約チートシートを表示(自動注入の手動版) |
| `env status\|rebuild` | venv の状態確認/再構築 |

## 6. 嵌合較正(skill 所有・中核)

### データモデル `calibration.toml`
```toml
# 既定 seed (調査の実数)。実機較正で上書きする。
[printer."generic_FDM".PLA]
nozzle = 0.4
fit.clearance = 0.20   # per side, 緩い (自由可動)
fit.sliding   = 0.10
fit.friction  = 0.05
fit.press     = -0.10  # 圧入 (穴を縮める)
elephant_foot = 0.15

[printer."generic_FDM".PETG]
nozzle = 0.4
fit.clearance = 0.25
fit.sliding   = 0.13
fit.friction  = 0.07
fit.press     = -0.08
elephant_foot = 0.20

[printer."generic_SLA".resin]
fit.clearance = 0.10
fit.sliding   = 0.06
fit.friction  = 0.03
fit.press     = -0.05
elephant_foot = 0.0
```
> 既定値は調査ベースの**安全寄り出発点**(FDM は穴が縮む傾向)。プリンタ実機は `calib gauge` で確定し上書きする。ユーザー固有プリンタは `[printer."<名>".<素材>]` を追加。

### `fits.py`(モデルが import)— セマンティクスを明示(レッドチーム反映)
**較正値は「設計上のクリアランス」ではなく、実機ガウジで実測した経験オフセット**(FDM の「穴が縮む」分を織り込んだ、その嵌合を得るために CAD 寸法へ与えるべき差分)と定義する。符号と適用先を曖昧にしない。
```python
from cad_print.fits import hole, peg, gap
# model.toml の printer/material/axis を解決して較正値を適用
hole_d = hole(nominal=10, fit="clearance")   # 穴=相手ペグ径 + 較正gap。穴を“ちょうど嵌る”寸法に
peg_d  = peg(nominal=10, fit="clearance")     # 代わりにペグ側を縮めたい時 (穴を動かせない場合)
fit_d  = peg(nominal=10, fit="press", mode="interference")  # 圧入: 干渉量を選択 (ペグ太らせ or 穴縮め)
g      = gap(fit="sliding", axis="z")         # リブ/蓋の片側ギャップ。軸別 (xy/z) で異方性に対応
```
- **適用先の明示**: 「穴を広げる」か「ペグを縮める」かを呼び出し側が選ぶ(両方を勝手に動かさない)。
- **圧入(press)**: `mode="interference"` で干渉量を与え、ペグを太らせる/穴を縮めるを選択。
- **elephant_foot は径オフセットにしない**: 底面の膨らみは**底面 chamfer(例 0.4–0.6mm@45°)推奨**として別管理(`fit()` の径計算に混ぜない)。
- **XY/Z 異方性**: `axis="xy"|"z"` で別値を引ける。較正テーブルも軸別を許容。

**狙い**: マジックナンバー禁止 + 物理的に正しい方向。較正を一点管理し、実機較正の更新を全モデルへ即反映。

### 較正ループ
`calib gauge`(向きマーカー + 印刷手順つき)→ 実機印刷 → 嵌合確認 → `calib set sliding 0.12 [--axis z]` → 以後 `fit("sliding")` が更新値を返す。`reference/fit-calibration.md` に手順(ガウジの向き、elephant foot、XY/Z 差、素材差、ノズル摩耗による経時変化)を集約。**未較正の素材で `export` する際は警告**(seed 値のままの可能性を明示)。

## 6.5 反復ループのガバナンス(レッドチーム反映)

振動/無限ループ/主観的停止を防ぐ:
- **比例調整**: 診断は pass/fail でなく **measured/threshold/margin** を返し、エージェントは margin に応じて寸法を比例調整(過補正しない=ダンピング)。
- **停止条件**: ①全 assertion pass **かつ** ②視覚的に妥当、を満たすか、③**反復上限**(既定 6 回)到達でユーザーにエスカレーション。
- **単調改善要件**: 反復間で失敗 margin の総和が改善しない場合は「振動/手詰まり」と判断し停止して人間に渡す。
- **ヒステリシス回避**: 閾値直近(例 margin < 5%)は「ギリギリ pass」として一度だけ余裕を持たせる調整を許し、往復を防ぐ。

## 7. 診断(skill 自前 + cad-khana は HLR のみ)

> **境界の反転(レッドチーム反映)**: 干渉/クリアランス/肉厚/オーバーハングは build123d/trimesh で自前実装する。安全クリティカルかつ数行で書け、pre-alpha 依存に委ねるべきでないため。cad-khana は唯一非自明な **HLR 線画(`khana draw`)** に縮退して活用(§8)。

### skill 自前(`diagnostics.py`)
- **干渉**: `(a & b)` の体積 > epsilon で判定。epsilon は設定可能。**独立クロスチェック**として bbox 重なり + `distance_to==0` も併用し silent 誤判定を防ぐ。
- **クリアランス**: `a.distance_to(b)`(OCCT, 堅牢)。閾値は `fit()` 名で指定可。
- **肉厚**: **trimesh voxel/SDF を主**(内接距離)で評価し、ray は補助。**細リブ/テーパーは ray が逸れて過大評価しがち**なので、サンプル分散が大きい/局所最小が閾値近傍の箇所を **"要目視" フラグ**で明示。素材/ノズルから既定 `wall_min`(例 FDM 0.4mm → ≈2×ライン幅)。
- **オーバーハング**: 三角法線×ビルド方向で角度算出(標準手法)、`overhang_max_deg` 既定は素材依存。
- 出力は skill 正規化スキーマ `diagnostics.json`(parts: bbox/volume/area/com/validity、interferences、clearances、wall、overhang、各 assertion は **measured/threshold/margin/passed**)。

### cad-khana(optional・vendored + pin)
- **`khana draw`** の HLR 線画(§8)。**vendored**(使う部分のみ取り込み)+ コミット pin。
- 不在/失敗でも skill 単独で診断とシェーディング描画が回る(**degradable**)。
- 将来 Assembly/joint/animation を使う場合のみ薄いアダプタで接続。

### assertion の宣言(任意)
`model.toml` に宣言的に書ける形も検討: `[[assert]] kind="clearance" a="lid" b="box" min="sliding"`(較正名で閾値指定)。Python 直書きと併存。

## 8. 描画(両方 — 形=シェーディング、寸法=線画)

### シェーディング多視点(skill・`render_shaded.py`)
- build123d → STL → `trimesh.load` → `pyrender` OffscreenRenderer。
- バックエンド選択順: **EGL(GPU)→ OSMesa(CPU)→ xvfb-run フォールバック**。`PYOPENGL_PLATFORM` を設定。
- 視点: iso/front/top(必要に応じ right/back)。各 PNG を `outputs/views/` に。寸法グリッド/スケールバー任意。
- 用途: Claude が**形の妥当性**を直接視認(マルチモーダル)。

### 線画 正投影/等角(khana draw)= GL 不要フォールバックも兼ねる
- `khana draw --view top,front,right,iso_ne --format png` → HLR 線画(1200²)。**OCCT 投影で GL を使わない**。
- 用途: 寸法把握・オーバーハング/隠れ線の確認、**かつシェーディングが GL 全滅した時の視覚ループ継続手段**。
- 代替経路: `build123d-mcp` の `render_view`(将来 opt-in)。

### GL フォールバック順序(明示)
1. EGL(GPU)→ 2. OSMesa(CPU ソフトウェア)→ 3. xvfb-run。すべて不可なら **4. HLR 線画のみで継続**(視覚ループは劣化するが停止しない)。
> 注: `trimesh.Scene.save_image()` は内部で OpenGL(pyglet)を使うため GL 不要の代替にはならない(レッドチームの該当案は不採用)。CPU 純ソフトの最終手段が必要なら matplotlib trisurf の粗描画を将来オプションに。

## 9. 環境 bootstrap(ADR-0005 踏襲)

- `ensure_cad_env.py`: 冪等。`~/.cache/cad-print/venv` に `uv venv` で build123d / cadquery-ocp(OCP)/ trimesh / pyrender /(vendored+pin した)cad-khana を導入。**全依存をバージョン pin**(cad-khana だけでなく build123d/OCP/trimesh/pyrender も。OCP/build123d の非互換は上流で頻発するため)。`flock` で worktree 並列の同時構築を直列化(初回構築中の待ちは進捗表示で明示)。
- **システムライブラリの確認**: OCP/GL は pip 外の OS パッケージ(`libgl1` / `libosmesa6` / `libegl1` / `xvfb` 等)を要する。bootstrap が**有無を検査し、不足を `apt` 手順で案内**(自動 sudo はしない)。GL が一切無くても §8 の HLR 線画で動作継続可能。
- ネットワーク断・clone 失敗時は**リトライ + 明確なエラー**(キャッシュ不在初回は中断、再実行で再開)。
- `env status` で健全性(pin 整合・GL 可否・khana 可否)、`env rebuild` で作り直し。常駐させない。

### スクリプト実行の分離(レッドチーム反映)
`part.py` は **`build` の度に subprocess + タイムアウト**で実行(無限ループ/暴走を遮断、巻き込み事故を防ぐ)。出力は**プロジェクト固有の `outputs/`**(cwd 配下)に隔離し、worktree 並列でのファイル衝突を避ける。venv は read-only 共有。

## 10. build123d 記述規約(注入する要点)

- 単位 **mm 既定**(`MM/CM/IN` 定数)。`import build123d as bd`(glob import 回避)。
- **selector は index 禁止**: `faces().sort_by(Axis.Z)[-1]` 等、`sort_by`/`filter_by(GeomType.*)` で安定化(topological naming 回避)。
- 配置は `.moved()` 後付けでなく **`Locations` コンテキスト**で生成時に。
- **パラメータは dataclass に集約**し派生寸法を計算(部品ファミリ化)。マジックナンバー禁止 → `fit()` 経由。
- **fillet/chamfer は最後**に(複雑度を上げる操作を後ろへ)。2D を固めてから 3D。
- 嵌合・肉厚など**製造制約は `fit()`/しきい値**で表現し、診断 assertion と対応づける。

詳細は `reference/build123d-conventions.md`。

## 11. プロジェクト連携

- `model.toml`: パラメータ + `printer`/`material`(較正解決に使用)+ 任意 `[[assert]]`。
- `part.py`: 雛形は規約準拠 + `from cad_print.fits import ...`。
- 造形指示はチャット or `spec.md`。Claude が指示→ part.py に落とし、`/cad-print build` で回す。

## 12. 受け入れ基準(実装フェーズの DoD)

1. `init`→`build` で雛形が診断+シェーディング/線画 PNG を生成し、Claude が画像を視認できる。
2. 干渉/クリアランス assertion が pass/fail と実測値を返し、失敗時に Claude が値を読んで自律調整できる。
3. `fit()` が calibration.toml を反映し、`calib set` の更新が次 build に効く。
4. `export` が STEP/STL を出力、STL がスライサで読める。
5. ヘッドレス描画が ubuntu-ws で成立(EGL/OSMesa/xvfb のいずれか)。
6. cad-khana を pin コミットに固定し、アダプタ経由でスキーマ差異に耐える。

## 13. リスクと対策

| リスク | 対策 |
|---|---|
| cad-khana pre-alpha の churn / 消失 | **診断を自前化**して依存を HLR 線画のみに縮退 + **vendored + 全依存 pin**。khana 不在でも degradable |
| khana/上流の silent 誤診断 | 安全クリティカルな干渉は**独立クロスチェック**。診断は measured 値も出して妥当性を可視化 |
| ヘッドレス GL 不可 | EGL→OSMesa→xvfb→**HLR 線画(GL 不要)** の順で必ず継続。bootstrap が GL 可否を検査 |
| OCP/build123d の非互換 | **全依存をバージョン pin**。`env status` で整合検査 |
| OCP 巨大・初回重い | オンデマンド venv + 進捗表示。常駐させない |
| 肉厚の見逃し(細リブ/テーパー) | **voxel/SDF を主**、ray は補助。疑わしい箇所を "要目視" フラグ |
| 嵌合較正の物理誤り | `fit()` の符号/適用先を明示、較正値=実測経験オフセット、elephant_foot は別管理、XY/Z 軸別 |
| ループ振動/無限 | measured マージンで比例調整 + 反復上限 + 単調改善 + エスカレーション(§6.5) |
| 任意コード/無限ループ | `part.py` を subprocess + timeout 実行、outputs 隔離 |
| selector の脆さ | index 禁止 + 位置述語/group_by/タグ。毎回スクラッチ再構築で staleness を持ち越さない |

## 14. 未解決の論点(レビューで詰める)

- スキル名 `/cad-print` で確定か(`/cad`・`/b123d` 等)。
- `model.toml` の宣言的 assert DSL を入れるか、Python 直書きに留めるか。
- 既定較正の初期エントリ(実プリンタ/素材)。**ユーザーのプリンタ/素材を確認して seed する。**
- 描画の既定視点セットと解像度。
- cad-khana の pin 方針(タグ無し → コミット固定 / fork するか)。
