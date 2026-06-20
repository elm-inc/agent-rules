#!/usr/bin/env python3
"""cad-print CLI — build123d × 3D プリンタ造形の媒介。

横断知識(規約・嵌合較正・診断・視覚ループ・env)を束ねる。重い build123d/OCP は
専用 venv (ensure_cad_env) に隔離し、part.py は subprocess + timeout で実行する。

サブコマンド:
  init [dir]                       プロジェクト雛形を展開 (part.py / model.toml / calibration.toml)
  build <part.py> [--timeout S]    env 確認 → 診断 + シェーディング描画 + STL 出力 (主ループ)
  check <part.py>                  診断のみ (高速・描画/出力なし)
  render <part.py>                 描画のみ
  export <part.py> --format F      最終出力 (step|stl|3mf|all)
  fit list|get <type>              較正値の参照 (--printer/--material で対象指定)
  calib gauge [--out f]            クリアランス試験ガウジ STL を生成 (実機較正用)
  conventions                      build123d 記述規約チートシートを表示
  env status|rebuild               venv の状態確認 / 再構築
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
TEMPLATES = SKILL / "templates"
REFERENCE = SKILL / "reference"
ENSURE = SCRIPTS / "ensure_cad_env.py"
WORKER = SCRIPTS / "_worker.py"


def venv_python(rebuild=False, quiet=True) -> str:
    args = [sys.executable, str(ENSURE)]
    if rebuild:
        args.append("--rebuild")
    if quiet:
        args.append("--quiet")
    r = subprocess.run(args, capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        sys.exit("error: cad-print env の構築に失敗。`cad_print.py env rebuild` を試してください")
    return r.stdout.strip().splitlines()[-1]


def run_worker(action, part, model, out, timeout, extra=None):
    py = venv_python()
    cmd = [py, str(WORKER), action, str(part), str(model or "-"), str(out)]
    if extra:
        cmd += extra
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"error: part.py の実行が {timeout}s を超過 (無限ループ/重すぎ?)。"
                 f"--timeout で延長できます")
    sys.stderr.write(r.stderr)
    summary = None
    for line in r.stdout.splitlines():
        if line.startswith("__CADPRINT_SUMMARY__ "):
            summary = json.loads(line[len("__CADPRINT_SUMMARY__ "):])
        else:
            print(line)
    if r.returncode != 0 and summary is None:
        sys.exit(r.returncode or 1)
    return summary


def _model_path(part: Path):
    m = part.parent / "model.toml"
    return m if m.exists() else None


def report(summary: dict):
    if not summary:
        return
    print()
    if "printer" in summary:
        print(f"printer: {summary['printer']} / {summary.get('material','')}")
    if "assertions" in summary:
        st = summary.get("status")
        print(f"診断: {st}  (fail {summary.get('failed',0)}/{len(summary['assertions'])})")
        for a in summary["assertions"]:
            print(f"  [{'OK' if a['passed'] else 'NG'}] {a['detail']}")
        print(f"  → {summary.get('diagnostics')}")
    if "views" in summary:
        print(f"描画 ({summary.get('render_backend')}):")
        for k, v in summary["views"].items():
            print(f"  {k}: {v}")
        if summary.get("line_art"):
            print(f"  線画(HLR): {summary['line_art']}")
    if "exports" in summary:
        print("出力:")
        for k, v in summary["exports"].items():
            print(f"  {k}: {v}")


# ---------- subcommands ----------

def cmd_init(args):
    dst = Path(args.dir)
    dst.mkdir(parents=True, exist_ok=True)
    pairs = [("part.py.tmpl", "part.py"), ("model.toml.tmpl", "model.toml"),
             ("calibration.toml", "calibration.toml")]
    for src, name in pairs:
        s, d = TEMPLATES / src, dst / name
        if d.exists():
            print(f"skip (既存): {d}")
        else:
            shutil.copy(s, d)
            print(f"作成: {d}")
    print(f"\n次: {dst}/part.py を編集 → `cad_print.py build {dst}/part.py`")


def cmd_build(args):
    part = Path(args.part)
    report(run_worker("build", part, _model_path(part), part.parent / "outputs", args.timeout))


def cmd_check(args):
    part = Path(args.part)
    report(run_worker("check", part, _model_path(part), part.parent / "outputs", args.timeout))


def cmd_render(args):
    part = Path(args.part)
    report(run_worker("render", part, _model_path(part), part.parent / "outputs", args.timeout))


def cmd_export(args):
    part = Path(args.part)
    report(run_worker("export", part, _model_path(part), part.parent / "outputs",
                      args.timeout, extra=[args.format]))


def cmd_fit(args):
    py = venv_python()
    code = (
        "import fits, json, sys\n"
        f"fits.set_context({args.printer!r}, {args.material!r})\n"
        "info=fits.printer_info()\n"
        "if %r=='list':\n" % args.fit_cmd +
        "    print(json.dumps(info, ensure_ascii=False, indent=2))\n"
        "else:\n"
        f"    print(fits.fit_value({args.type!r}) if {args.type!r} else json.dumps(info))\n"
    )
    r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                       env={**__import__("os").environ, "PYTHONPATH": str(SCRIPTS)})
    sys.stderr.write(r.stderr)
    print(r.stdout, end="")


def cmd_calib(args):
    if args.calib_cmd == "gauge":
        py = venv_python()
        out = args.out or "clearance-gauge.stl"
        # 向きマーカー付きクリアランス試験: 固定ペグ + 段階穴
        code = f"""
import build123d as bd
with bd.BuildPart() as g:
    bd.Box(70, 16, 6)
    pegs = [0.0, 0.1, 0.2, 0.3, 0.4]   # 直径差(片側*2 相当のトータル)
    with bd.Locations(*[((-30+ i*15), 0, 3) for i in range(5)]):
        bd.Cylinder(radius=4, height=6, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    # 向きマーカー(右端に小突起)
    with bd.Locations((34, 6, 3)):
        bd.Box(2, 2, 4, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
bd.export_stl(g.part, {out!r})
print("gauge → {out} (各ペグ径 8.0/8.2/8.4/8.6/8.8mm 相当。受け穴を別途用意し嵌合確認)")
"""
        r = subprocess.run([py, "-c", code], capture_output=True, text=True)
        sys.stderr.write(r.stderr)
        print(r.stdout, end="")
        print("実機印刷 → 嵌合確認 → `calib set <type> <mm>` で calibration.toml を更新 "
              "(reference/fit-calibration.md 参照)")
    else:
        print("calib set は calibration.toml を直接編集してください "
              "(該当 [printer.<名>.<素材>] の fit.<type>)。手順: reference/fit-calibration.md")


def cmd_conventions(args):
    f = REFERENCE / "build123d-conventions.md"
    print(f.read_text() if f.exists() else "(規約ファイル未配置)")


def cmd_env(args):
    if args.env_cmd == "rebuild":
        venv_python(rebuild=True, quiet=False)
        print("env: 再構築完了")
    else:
        subprocess.run([sys.executable, str(ENSURE), "--check-gl"])


def build_parser():
    p = argparse.ArgumentParser(prog="cad_print", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("dir", nargs="?", default="."); s.set_defaults(f=cmd_init)
    for name, fn in [("build", cmd_build), ("check", cmd_check), ("render", cmd_render)]:
        s = sub.add_parser(name); s.add_argument("part")
        s.add_argument("--timeout", type=int, default=180); s.set_defaults(f=fn)
    s = sub.add_parser("export"); s.add_argument("part")
    s.add_argument("--format", default="stl", choices=["step", "stl", "3mf", "all"])
    s.add_argument("--timeout", type=int, default=180); s.set_defaults(f=cmd_export)

    s = sub.add_parser("fit"); s.add_argument("fit_cmd", choices=["list", "get"])
    s.add_argument("type", nargs="?"); s.add_argument("--printer"); s.add_argument("--material")
    s.set_defaults(f=cmd_fit)

    s = sub.add_parser("calib"); s.add_argument("calib_cmd", choices=["gauge", "set"])
    s.add_argument("--out"); s.set_defaults(f=cmd_calib)

    s = sub.add_parser("conventions"); s.set_defaults(f=cmd_conventions)
    s = sub.add_parser("env"); s.add_argument("env_cmd", choices=["status", "rebuild"])
    s.set_defaults(f=cmd_env)
    return p


def main():
    args = build_parser().parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
