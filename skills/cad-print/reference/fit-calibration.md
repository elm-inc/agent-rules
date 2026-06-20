# 嵌合較正(cad-print)

3D プリントの嵌合は **プリンタ × 素材**で変わる。`calibration.toml` に経験値を持ち、`fit()` で全モデルが
参照する。値は「設計上の理想隙間」ではなく **その嵌合を実機で得るための経験オフセット**(FDM の穴縮み等を
織り込む)。

## 値の意味

| キー | 意味 |
|---|---|
| `clearance` | 自由可動。ラジアル**片側**ギャップ [mm] |
| `sliding` | すべり嵌合(手で動く)。片側ギャップ |
| `friction` | 圧入手前のきつめ。片側ギャップ |
| `press` | 圧入。**負値 = 片側干渉量** |
| `elephant_foot_chamfer` | 底面に推奨する面取り [mm@45°](径計算と分離) |
| `shrink_comp` | 高温材の線収縮率(`shrink_scale()` で全体寸法補正) |

`fit()` の適用(符号と適用先を明示):
```
hole(nominal, "clearance") = nominal + 2*gap   # 穴を両側に広げる
peg (nominal, "sliding")   = nominal - 2*gap   # 穴を動かせない時はペグを縮める
gap ("sliding")            = gap               # リブ/蓋の片側隙間
press は gap<0 なので hole("press")=穴縮め / peg("press")=ペグ太らせ で干渉
```
軸別異方性は `clearance = { xy = 0.12, z = 0.14 }` と書ける(`fit_value(..., axis="z")`)。

## 既定 seed(Bambu)

- **A1 mini**(オープン・180³): PLA/PETG/TPU。PLA clearance 0.12 / sliding 0.08 / press -0.10。
- **X2D**(密閉・デュアル・256³級)/ **H2D**(密閉・350×320×325): + ABS/ASA/PC/PA-CF。高温材は `shrink_comp` あり。

いずれも**安全寄りの出発点**。実機で必ず較正して上書きする。

## 実機較正の手順

1. `cad_print.py calib gauge --out gauge.stl` でクリアランス試験ガウジを生成(向きマーカー付き)。
2. 対象プリンタ × 素材 × 実プロファイルで印刷。
3. 受け側(穴)を別途用意し、各段のペグと嵌合を確認。「手で気持ちよく動く」段が **sliding**、
   緩く落ちる段が **clearance**、強く押して入る段が **friction/press**。
4. その片側ギャップを `calibration.toml` の該当 `[printer.<名>.<素材>]` に記入(`calib set` は現状ファイル直接編集)。
5. 以後 `fit("sliding")` 等が更新値を返し、全モデルへ即反映。

## 落とし穴(必ず意識)

- **FDM は穴が縮む**(ノズルの内側ふくらみ)。`fit()` の経験値はこれを織り込む前提。スライサの
  XY サイズ補正を併用する場合は二重補正に注意。
- **elephant foot**(底面の広がり)は底面 chamfer で対処。径オフセットに混ぜない。
- **XY と Z で精度が違う**(Z は層厚で安定、XY はベルト等でぶれる)。print-in-place ヒンジ等は軸別較正を検討。
- **素材差**(PLA→PETG はおおむね +0.05mm 程度緩める)。**ノズル摩耗**で経時変化 → 定期再較正。
- **未較正の素材**で `export` すると seed のまま。重要部品は試し刷りしてから量産。
