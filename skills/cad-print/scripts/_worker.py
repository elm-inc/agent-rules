"""cad-print の in-venv ワーカー。venv python から実行され、build123d を扱う。
cad_print.py(システム python)から subprocess + timeout で起動される。

usage: _worker.py <action> <part.py> <model.toml|-> <out_dir>
  action: build | check | render | export
出力: stdout 末尾に JSON サマリ(呼び出し側が拾う)
"""
from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))  # fits / diagnostics / render_shaded を import 可能に


def load_model_toml(p: str) -> dict:
    if p == "-" or not Path(p).exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def resolve_parts(ns: dict) -> dict:
    if "parts" in ns and isinstance(ns["parts"], dict):
        return ns["parts"]
    if "part" in ns:
        return {"part": ns["part"]}
    raise SystemExit("part.py は `part`(単一) か `parts`(dict) を定義してください")


def build_checks(ns: dict):
    """part.py の checks から (clearances, interferences) を作る。
    clearance の閾値が文字列なら fits の較正名として解決。"""
    import fits
    clearances, interferences = [], []
    for c in ns.get("checks", []) or []:
        if "clearance" in c:
            a, b, thr = c["clearance"]
            mn = fits.gap(thr) if isinstance(thr, str) else float(thr)
            clearances.append((a, b, mn))
        elif "interference" in c:
            a, b = c["interference"]
            interferences.append((a, b))
    return clearances, interferences


def combined_mesh(parts: dict):
    import trimesh
    from diagnostics import to_trimesh
    meshes = [to_trimesh(p) for p in parts.values()]
    return trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]


def export_object(parts: dict):
    import build123d as bd
    if len(parts) == 1:
        return next(iter(parts.values()))
    return bd.Compound(children=list(parts.values()))


def do_export(parts: dict, out_dir: Path, fmt: str) -> dict:
    import build123d as bd
    obj = export_object(parts)
    out = {}
    base = out_dir / "model"
    fmts = [fmt] if fmt != "all" else ["step", "stl", "3mf"]
    for f in fmts:
        try:
            if f == "step":
                bd.export_step(obj, str(base.with_suffix(".step")))
                out["step"] = str(base.with_suffix(".step"))
            elif f == "stl":
                bd.export_stl(obj, str(base.with_suffix(".stl")))
                out["stl"] = str(base.with_suffix(".stl"))
            elif f == "3mf":
                m = bd.Mesher()
                m.add_shape(obj)
                m.write(str(base.with_suffix(".3mf")))
                out["3mf"] = str(base.with_suffix(".3mf"))
        except Exception as e:  # noqa
            out[f + "_error"] = str(e)
    return out


def main() -> int:
    action, part_path, model_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model = load_model_toml(model_path)

    printer_cfg = model.get("printer", {})
    if printer_cfg.get("name"):
        os.environ["CAD_PRINT_PRINTER"] = str(printer_cfg["name"])
    if printer_cfg.get("material"):
        os.environ["CAD_PRINT_MATERIAL"] = str(printer_cfg["material"])
    proj_cal = Path(part_path).resolve().parent / "calibration.toml"
    if proj_cal.exists():
        os.environ.setdefault("CAD_PRINT_CALIBRATION", str(proj_cal))

    # part.py を実行 (この subprocess 自体が cad_print.py 側で timeout 管理されている)
    ns = runpy.run_path(part_path)
    parts = resolve_parts(ns)

    import fits
    pinfo = fits.printer_info()
    summary = {"action": action, "printer": pinfo["printer"], "material": pinfo["material"],
               "out_dir": str(out)}

    if action in ("build", "check"):
        import diagnostics as dg
        clr, itf = build_checks(ns)
        diag = dg.diagnose(parts, pinfo, clearances=clr, interferences=itf)
        dj = out / "diagnostics.json"
        dj.write_text(json.dumps(diag, ensure_ascii=False, indent=2))
        summary["diagnostics"] = str(dj)
        summary["status"] = diag["status"]
        summary["failed"] = diag["summary"]["failed"]
        summary["assertions"] = [
            {"name": a["name"], "passed": a["passed"], "detail": a["detail"]}
            for a in diag["assertions"]
        ]

    if action in ("build", "render"):
        import render_shaded as rs
        views = model.get("render", {}).get("views")
        size = int(model.get("render", {}).get("size", 720))
        vsel = {k: rs.VIEWS[k] for k in views if k in rs.VIEWS} if views else rs.VIEWS
        r = rs.render(combined_mesh(parts), out / "views", views=vsel, size=size)
        summary["render_backend"] = r["backend"]
        summary["views"] = r["views"]
        # optional: HLR 線画 (khana, あれば)
        try:
            import khana_draw
            la = khana_draw.draw(Path(part_path), out / "line", views)
            if la:
                summary["line_art"] = la
        except Exception:
            pass

    if action in ("build", "export"):
        fmt = model.get("export", {}).get("format", "stl")
        if action == "export" and len(sys.argv) > 5:
            fmt = sys.argv[5]
        summary["exports"] = do_export(parts, out, fmt)

    print("\n__CADPRINT_SUMMARY__ " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
