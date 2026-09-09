#!/usr/bin/env python3
"""スライス — STL/3MF を「印刷できるファイル」に変える。

**プリンタは形を受け取れない。** STL や 3MF は形であって経路ではないので、
機体・ノズル・フィラメント・品質を決めて G-code に落とす段が要る。
`/cad-print` の build123d でも ai-cad でも出口は同じ STL/3MF なので、ここは
どちらからも使える独立した段にしてある。

**プロファイルのパスを毎回探さないためのスクリプト**である。Bambu Studio の
システムプロファイルは名前が長く、しかも罠がある:

- `Bambu Lab A1 mini.json` は**インスタンス化できない**基底プロファイルで、
  渡すと `from unsupported run found error, return -5` としか言わない。
  実際に要るのは `Bambu Lab A1 mini 0.4 nozzle.json`
- プロセスとフィラメントは機体コード (`A1M` など) で名前が分かれている
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: Bambu Studio のシステムプロファイル置き場。
BBL = Path.home() / ".config" / "BambuStudio" / "system" / "BBL"

#: 表示名 → プロファイル名に出てくる機体コード。
#: プロセス/フィラメントのファイル名がこのコードで分かれている。
MACHINE_CODES = {
    "A1mini": "A1M",
    "A1": "A1",
    "P1P": "P1P",
    "P1S": "P1P",
    "X1C": "X1C",
    "X1": "X1",
    "X2D": "X2D",
    "H2D": "H2D",
}

#: 表示名 → 機体プロファイルのファイル名 (ノズル付き。基底は使えない)。
MACHINE_FILES = {
    "A1mini": "Bambu Lab A1 mini {nozzle} nozzle.json",
    "A1": "Bambu Lab A1 {nozzle} nozzle.json",
    "P1P": "Bambu Lab P1P {nozzle} nozzle.json",
    "P1S": "Bambu Lab P1S {nozzle} nozzle.json",
    "X1C": "Bambu Lab X1 Carbon {nozzle} nozzle.json",
    "X2D": "Bambu Lab X2D {nozzle} nozzle.json",
    "H2D": "Bambu Lab H2D {nozzle} nozzle.json",
}


#: Bambu Studio のログ行。**年で判定しない** (2027 年に黙って効かなくなる)。
_LOG_LINE = re.compile(r"^\[\d{4}-\d{2}-\d{2} ")


def _tail(output: str, lines: int = 6) -> str:
    """ログ行を除いた末尾。エラーの手掛かりだけを残す。"""
    useful = [line for line in output.splitlines() if line.strip() and not _LOG_LINE.match(line)]
    return "\n".join(useful[-lines:]) or "(出力なし)"


class SliceError(Exception):
    """スライスできない。**候補を必ず添える** (名前が長いので当てずっぽうにさせない)。"""


def _pick(directory: Path, wanted: str, kind: str) -> Path:
    path = directory / wanted
    if path.is_file():
        return path
    # **候補を必ず出す。** 部分集合で絞ると 1 語違うだけで「一致なし」になり、
    # 名前が長いプロファイルでは当てずっぽうを強いることになる。重なりで並べる。
    want = _tokens(wanted.removesuffix(".json"))
    scored = []
    for candidate in directory.glob("*.json"):
        overlap = len(want & _tokens(candidate.stem))
        if overlap:
            scored.append((overlap, candidate.name))
    near = [name for _, name in sorted(scored, key=lambda s: (-s[0], s[1]))]
    hint = "\n".join(f"    {n}" for n in near[:8]) or "    (候補なし)"
    raise SliceError(f"{kind} プロファイルがありません: {wanted}\n  近いもの:\n{hint}")


def _tokens(name: str) -> set[str]:
    return {t.lower() for t in re.split(r"[ @._-]+", name) if t}


def resolve(printer: str, material: str, quality: str, nozzle: str) -> dict[str, Path]:
    """機体・プロセス・フィラメントのプロファイルを解決する。"""
    if not BBL.is_dir():
        raise SliceError(
            f"Bambu Studio のシステムプロファイルが見つかりません ({BBL})。"
            "Bambu Studio を一度起動すると作られます"
        )
    if printer not in MACHINE_FILES:
        raise SliceError(f"未知のプリンタです: {printer} (既知: {', '.join(MACHINE_FILES)})")
    code = MACHINE_CODES[printer]
    return {
        # **基底プロファイルではなくノズル付きを使う** (基底は instantiation=false)。
        "machine": _pick(BBL / "machine", MACHINE_FILES[printer].format(nozzle=nozzle), "機体"),
        "process": _pick(BBL / "process", f"{quality} @BBL {code}.json", "プロセス"),
        "filament": _pick(BBL / "filament", f"{material} @BBL {code}.json", "フィラメント"),
    }


def slice_model(
    model: Path,
    out_dir: Path,
    *,
    printer: str = "A1mini",
    material: str = "Bambu PLA Basic",
    quality: str = "0.20mm Standard",
    nozzle: str = "0.4",
    copies: int = 1,
    timeout: int = 900,
) -> dict[str, object]:
    """スライスして、印刷できる 3MF と統計を返す。"""
    if shutil.which("bambu-studio") is None:
        raise SliceError(
            "bambu-studio が PATH にありません。"
            "Bambu Studio を入れるか、スライスは GUI で行ってください"
        )
    if not model.is_file():
        raise SliceError(f"モデルがありません: {model}")
    profiles = resolve(printer, material, quality, nozzle)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{model.stem}.gcode.3mf"

    command = [
        "bambu-studio",
        "--load-settings", f"{profiles['machine']};{profiles['process']}",
        "--load-filaments", str(profiles["filament"]),
        "--slice", "0",
        "--export-3mf", name,
        "--outputdir", str(out_dir),
    ]
    if copies > 1:
        # **`--repetitions` ではない。** そちらは `return -2` で落ちる (実測)。
        # 複製して並べるのは `--clone-objects` + `--arrange`。
        command += ["--clone-objects", str(copies), "--arrange", "1"]
    command.append(str(model))

    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SliceError(
            f"スライスが {timeout} 秒で終わりませんでした。"
            "三角形が多すぎないか (--format mesh の三角形数) を確かめるか --timeout を伸ばしてください"
        ) from exc

    result_path = out_dir / "result.json"
    if done.returncode != 0 or not result_path.is_file():
        raise SliceError(f"スライスに失敗しました (rc={done.returncode})\n{_tail(done.stdout)}")

    try:
        report = json.loads(result_path.read_text("utf-8"))
        plate = report["sliced_plates"][0]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        # **壊れた result.json でトレースバックを出さない。** 直し方が分からなくなる。
        raise SliceError(
            f"スライス結果を読めません ({result_path}): {exc}\n{_tail(done.stdout)}"
        ) from exc
    placed = len(plate.get("objects", []))
    produced = out_dir / name
    if not produced.is_file():
        raise SliceError(f"3MF が書き出されていません: {produced}")
    return {
        "file": produced,
        "seconds": round(plate["total_predication"]),
        "grams": round(sum(f.get("total_used_g", 0.0) for f in plate.get("filaments", [])), 1),
        "triangles": plate.get("triangle_count", 0),
        "placed": placed,
        "bbox": plate["objects"][0]["bbox"] if plate.get("objects") else {},
        "layer_height": report["layer_height"],
        "walls": report.get("wall_loops"),
        "infill": report.get("sparse_infill_density"),
        "warning": plate.get("warning_message", ""),
        "profiles": {k: v.name for k, v in profiles.items()},
    }


def render(stats: dict[str, object]) -> str:
    box = stats.get("bbox") or {}
    minutes, seconds = divmod(int(stats["seconds"]), 60)  # type: ignore[arg-type]
    lines = [
        f"スライスしました: {stats['file']}",
        f"  印刷時間 : {minutes}分{seconds}秒",
        f"  外形     : {box.get('width', 0):.1f} x {box.get('depth', 0):.1f} x "
        f"{box.get('height', 0):.1f} mm  ({stats['triangles']} 三角形)",
        f"  配置     : {stats['placed']} 個",
        f"  設定     : {stats['profiles']['machine']}",
        f"             {stats['profiles']['process']} / {stats['profiles']['filament']}",
        f"             層 {stats['layer_height']:.2f}mm / 壁 {stats['walls']} 周 / "
        f"インフィル {stats['infill']}%",
    ]
    if stats["grams"]:
        lines.append(f"  使用量   : {stats['grams']} g")
    if stats["warning"]:
        # スライサの警告は**必ず出す**。薄すぎ・浮き・サポート不足はここに出る。
        lines.append(f"  ! 警告   : {stats['warning']}")
    lines.append("  microSD に入れて本体から選ぶか、Bambu Studio で開いて LAN 送信します")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover — cad_print.py 経由が主
    try:
        print(render(slice_model(Path(sys.argv[1]), Path(sys.argv[2] if len(sys.argv) > 2 else "."))))
    except SliceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
