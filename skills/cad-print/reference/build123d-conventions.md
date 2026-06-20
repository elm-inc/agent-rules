# build123d 記述規約(cad-print)

3D プリント向けに保守可能・再現可能・selector が壊れにくい build123d を書くための規約。
`/cad-print` の part.py はこれに従う。

## 基本

- **単位 mm 既定**。`import build123d as bd`(glob import しない)。定数 `MM/CM/IN` あり。
- **パラメータは dataclass に集約**し派生寸法を計算。マジックナンバー禁止。

```python
from dataclasses import dataclass
import build123d as bd

@dataclass
class Params:
    w: float = 40.0
    wall: float = 2.0
P = Params()
```

## 嵌合は fit() を使う(較正の一点管理)

```python
from fits import hole, peg, gap, elephant_foot_chamfer
hole_d = hole(12.0, "clearance")   # 穴を両側に広げる
pin_d  = peg(12.0, "sliding")       # ペグを縮める
lip_g  = gap("sliding")             # 片側ギャップ
```
直接 `+0.2` のような寸法直書きは禁止(プリンタ/素材で変わるため)。

## selector は安定化する(topological naming 対策)

build123d は static な面名を持たないが、**index 直指定は形状変更で壊れる**。位置・型・グループで指定する。

```python
# ✗ 脆い: 面の枚数や順序が変わると別の面を掴む
top = part.faces()[3]

# ✓ 安定: 軸で整列して端を取る / 型でフィルタ / グループで層を取る
top = part.faces().sort_by(bd.Axis.Z)[-1]
holes = part.edges().filter_by(bd.GeomType.CIRCLE)
bottom_edges = part.edges().group_by(bd.Axis.Z)[0]   # 最下層 = 接地面
```
- fillet/chamfer の**順序が変わると面数が変わる** → selector 後段がズレる。可能なら寸法から構築し、selector への依存を減らす。
- 同種面が複数ある時は位置(`sort_by`/`group_by` + index)で一意化する。

## 配置は Locations で(後付け .moved() を避ける)

```python
# ✓ 生成時に配置
with bd.Locations((10, 0, 0), (-10, 0, 0)):
    bd.Cylinder(radius=2, height=5)
```

## fillet / chamfer は最後に

複雑度を上げる操作は後段へ。2D スケッチを固めてから 3D 化。

```python
part = build_base(P)              # まず形を作る
ef = elephant_foot_chamfer()
if ef:                            # elephant foot 対策(底面)
    part = bd.chamfer(part.edges().group_by(bd.Axis.Z)[0], length=min(ef, 0.4))
```

## 3D プリント特有

- **オーバーハングは 45° 以内**を目安(超えるとサポートが要る → 診断が警告)。
- **最小肉厚 ≥ 2×ライン幅**(0.4mm ノズルで概ね ≥0.8–1.2mm)。診断は ray 近似なので**薄肉は PNG でも確認**。
- **ビルドボリューム**に収まるか(A1 mini は 180³ と小さい)。診断が自動チェック。
- **底面 chamfer** で elephant foot を緩和(径オフセットには混ぜない)。
- 高温材(ABS/ASA/PC)は収縮するため、必要なら `fits.shrink_scale()` を全体寸法に掛ける。

## part.py の出力契約

- `part`(単一)or `parts`({名前: obj})を定義。
- 嵌合検証は `checks` に宣言(`/cad-print` の SKILL.md 参照)。
