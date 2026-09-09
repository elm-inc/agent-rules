# スライス済み 3mf の作り方

プリンタが印刷できるのは、`Metadata/plate_N.gcode` を含む**スライス済みの 3mf** だけ。
形状だけの 3mf / STL / STEP は送っても印刷できない (`bambu-send` は送る前に弾く)。

## GUI (普通はこちら)

Bambu Studio でスライスしたあと **「プレートをエクスポート」→ `.3mf`**。
「送信」ボタンでも同じことが起きる (このスキルはその経路を CLI から行うもの)。

## CLI

```bash
P=~/.config/BambuStudio/system/BBL
bambu-studio \
  --load-settings "$P/machine/Bambu Lab A1 mini 0.4 nozzle.json;$P/process/0.20mm Standard @BBL A1M.json" \
  --load-filaments "$P/filament/Bambu PLA Basic @BBL A1M.json" \
  --slice 0 \
  --export-3mf part.3mf \
  --outputdir /path/to/out \
  part.stl
```

### CLI の癖 (実測)

- **`--export-3mf` には裸のファイル名を渡す。** `--outputdir` と**連結される**ので、
  絶対パスを渡すと `<outputdir>/<絶対パス>` になり `return -13` で落ちる
- **`--load-settings` は machine と process を `;` 区切りで両方渡す。**
  `machine_model` ではなく **machine (ノズル径つき)** でないと `return -5`
- ヘッドレス環境では `glfwInit return error, code 65544` が出るが、**3mf は出来ている**
- 出来た 3mf には `Metadata/plate_1.gcode` と `Metadata/plate_1.gcode.md5` が入る。
  `bambu-send` はこの 2 つを突き合わせてから送る

## 中身の確かめ方

```bash
python3 -c "
import zipfile
z = zipfile.ZipFile('part.3mf')
for n in z.namelist(): print(f'{z.getinfo(n).file_size:>9} {n}')
"
```
