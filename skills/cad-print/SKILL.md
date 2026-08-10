---
name: cad-print
description: build123d で 3D プリンタ造形を「書く→診断→視認→調整」で反復。嵌合較正 fit() で一点管理し干渉/肉厚/オーバーハングを自前診断、多視点 PNG で視認、STEP/STL/3MF 出力。Bambu A1 mini/X2D/H2D 対応。3Dモデリング・CAD・3Dプリント・造形指示のときに使用
argument-hint: "<subcommand> [args] | init <dir> | build <part.py> | check | render | export --format | fit | calib gauge | conventions | env"
disable-model-invocation: false
allowed-tools: Bash(python3 ~/repos/github.com/elm-inc/agent-rules/skills/cad-print/scripts/cad_print.py*) Bash(python3 ~/.claude/skills/cad-print/scripts/cad_print.py*) Bash(uv *) Bash(ls *) Bash(cat *) Bash(test *) Read Write Edit
---

# cad-print — build123d × 3D プリンタ造形

横断知識(記述規約・嵌合較正・診断・視覚フィードバック・環境)を束ねる媒介スキル。各プロジェクトは
具体的な造形指示だけを与え、本スキルが「書く→診断→視認→調整」のループを回す。
設計判断: [`docs/adr/0007`](../../docs/adr/0007-build123d-3d-printing-cad-skill.md) / 詳細: [`docs/design/cad-print-skill.md`](../../docs/design/cad-print-skill.md)

## 反復ループ(使い方の核)

```
造形指示 → part.py を規約準拠で記述/修正 (fit() で較正値を参照)
  → cad_print.py build part.py
       env 確認 → 自前診断 (干渉/クリアランス/肉厚/オーバーハング/ビルドボリューム)
                → シェーディング多視点 PNG
  → diagnostics.json (measured/threshold/margin) を読む + PNG を“見る”(マルチモーダル)
  → fail or 形が違う → パラメータ/形状を調整して再ループ (※比例調整・反復上限・収束しなければ人に渡す)
  → pass かつ妥当 → export で STEP/STL/3MF
```

## 実行

`scripts/cad_print.py` を**システム python3** で実行する(重い build123d/OCP は専用 venv に隔離され、
スキルが自動構築・呼び出す。part.py は subprocess + timeout で実行)。

```bash
python3 ${SKILL_DIR}/scripts/cad_print.py <subcommand> [args]
```
手動では `~/.claude/skills/cad-print/scripts/cad_print.py`(install.sh 後の symlink)。

## サブコマンド

| コマンド | 説明 |
|---|---|
| `init [dir]` | 雛形展開 (part.py / model.toml / calibration.toml) |
| `build <part.py> [--timeout S]` | 診断 + 描画 + STL 出力(**主ループ**)。出力は `<part.py の dir>/outputs/` |
| `check <part.py>` | 診断のみ(高速) |
| `render <part.py>` | 描画のみ |
| `export <part.py> --format step\|stl\|3mf\|all` | 最終出力 |
| `fit list [--printer P --material M]` / `fit get <type>` | 較正値の確認 |
| `calib gauge [--out f]` | クリアランス試験ガウジ STL を生成(実機較正用) |
| `conventions` | build123d 記述規約チートシート |
| `env status\|rebuild` | venv 状態確認 / 再構築 |

## part.py の契約

- `part` (単一 build123d オブジェクト) **または** `parts` ({名前: オブジェクト} dict)
- `checks` (任意): 部品ペア診断
  - `{"clearance": ["a","b", 0.1]}` 最小距離 ≥0.1mm(数値 or 較正名 `"sliding"` 等)
  - `{"interference": ["a","b"]}` 干渉禁止
- 嵌合は `from fits import hole, peg, gap` を使う(`model.toml` の printer/material で較正解決)。

雛形 `templates/part.py.tmpl` がそのまま動く実例(ピン&穴のすべり嵌合)。

## 嵌合較正(中核)

`calibration.toml`(プロジェクトに展開、無ければ skill 既定)に **Bambu A1 mini / X2D / H2D × 素材**の
seed。`fit()` で一点管理:
- `hole(nominal, "clearance")` = 穴を両側に広げる / `peg(nominal, "sliding")` = ペグを縮める
- `gap("sliding")` = 片側ギャップ / `press` は負値で干渉(圧入)
- 値は**実機ガウジの経験オフセット**。`calib gauge` で印刷→嵌合確認→`calibration.toml` を更新。
詳細: [`reference/fit-calibration.md`](reference/fit-calibration.md)

## 記述規約(必ず守る)

mm 既定 / selector は index 禁止(`sort_by`/`group_by`/`filter_by` + 位置)/ 配置は `Locations` /
パラメータは dataclass に集約・マジックナンバー禁止(`fit()` 経由)/ fillet・chamfer は最後。
詳細: [`reference/build123d-conventions.md`](reference/build123d-conventions.md)

## 診断の読み方

`outputs/diagnostics.json` は各 assertion に `measured / threshold / margin / passed`。失敗時は **margin に
比例して**寸法を調整する(過補正しない)。肉厚は ray 近似で **"要目視" フラグ**付き — PNG と併せて判断。

## 環境・既知の制約

- 初回 `build` 時に専用 venv を自動構築(build123d/OCP/trimesh/matplotlib、数百MB・数分)。`env rebuild` で作り直し。
- **描画は既定 matplotlib(GL 不要・確実)**。`pyrender`(GL)は高品質だがカメラ調整が要・opt-in。
- **HLR 線画(cad-khana)は現状 optional・無効**(pre-alpha が現行 build123d と依存衝突)。シェーディングで代替。将来 vendoring。
- ヘッドレス GL は環境依存。matplotlib 経路は GL 不要なので常に動く。
