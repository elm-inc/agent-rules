#!/usr/bin/env python3
"""cad-print 専用 venv をオンデマンド構築する (ADR-0005 のオンデマンド env 方式)。

build123d / OCP は数百 MB 級で重い。PEP723 の毎回 ephemeral 解決は非現実的なので、
専用 venv (~/.cache/cad-print/venv) を一度だけ作り、以後は再利用する。

- 冪等: 既に import 可能なら即終了 (--rebuild で作り直し)
- flock で worktree 並列の同時構築を直列化
- 依存は lock ファイルに固定 (再現性)。OCP/build123d の上流非互換に備える
- cad-khana は optional (HLR 線画用)。失敗しても致命にしない (degradable)
- GL / OS ライブラリの有無を検査して案内 (シェーディング描画は EGL/OSMesa/xvfb が要る)

usage:
  python3 ensure_cad_env.py [--rebuild] [--with-khana] [--quiet]
  → 成功時 stdout 最終行に venv python の絶対パスを出力 (呼び出し側が拾う)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

CACHE = Path(os.environ.get("CAD_PRINT_CACHE", str(Path.home() / ".cache" / "cad-print")))
VENV = CACHE / "venv"
LOCK = CACHE / "requirements.lock"
LOCKFILE = CACHE / ".envlock"
KHANA_MARKER = CACHE / ".khana-ok"

# 第一段 (v1) の依存。安全寄りに floor 指定 → 構築後に freeze して lock 固定。
CORE_DEPS = [
    "build123d>=0.8",   # OCP (OpenCASCADE) を引き込む。CAD カーネル本体
    "trimesh>=4.0",     # メッシュ診断 (肉厚 ray・オーバーハング)・STL I/O
    "rtree>=1.0",       # trimesh の ray/近接に必須の空間インデックス
    "scipy>=1.11",      # trimesh の各種計算が利用
    "numpy>=1.24",
    "pyrender>=0.1.45", # シェーディング オフスクリーン描画 (GL 有り時の高品質経路)
    "matplotlib>=3.8",  # GL 不要の CPU フォールバック描画 (trisurf 多視点)
    "Pillow>=10.0",     # PNG 書き出し
]
# cad-khana: HLR 線画 (khana draw) 用。pre-alpha なのでコミット pin 推奨だが、
# v1 は optional 扱い。未導入でも skill は degradable に動く。
KHANA_SPEC = "git+https://github.com/cyberchitta/cad-khana"


def log(msg: str, quiet: bool):
    if not quiet:
        print(msg, file=sys.stderr)


def venv_python() -> Path:
    return VENV / "bin" / "python"


def importable() -> bool:
    py = venv_python()
    if not py.exists():
        return False
    code = "import build123d, trimesh, pyrender, numpy, PIL  # noqa"
    r = subprocess.run([str(py), "-c", code], capture_output=True)
    return r.returncode == 0


def uv() -> str:
    u = shutil.which("uv")
    if not u:
        sys.exit("error: uv が見つかりません。https://docs.astral.sh/uv/ で導入してください")
    return u


def build(rebuild: bool, with_khana: bool, quiet: bool):
    CACHE.mkdir(parents=True, exist_ok=True)
    if rebuild and VENV.exists():
        log("rebuild: 既存 venv を削除", quiet)
        shutil.rmtree(VENV, ignore_errors=True)
        KHANA_MARKER.unlink(missing_ok=True)

    if importable() and not rebuild:
        log(f"ok: venv 構築済み ({VENV})", quiet)
    else:
        log(f"build: venv を構築中… (OCP の DL で数分かかることがあります) {VENV}", quiet)
        subprocess.run([uv(), "venv", "--python", "3.12", str(VENV)], check=True)
        # lock があればそれを、無ければ floor 指定で解決
        if LOCK.exists() and not rebuild:
            subprocess.run([uv(), "pip", "install", "--python", str(venv_python()),
                            "-r", str(LOCK)], check=True)
        else:
            subprocess.run([uv(), "pip", "install", "--python", str(venv_python()),
                            *CORE_DEPS], check=True)
            # 解決結果を lock 固定 (再現性 / 上流非互換への備え)
            with LOCK.open("w") as f:
                subprocess.run([uv(), "pip", "freeze", "--python", str(venv_python())],
                               check=True, stdout=f)
            log(f"lock: 依存を固定 → {LOCK}", quiet)
        if not importable():
            sys.exit("error: venv 構築後も import に失敗。'env rebuild' を試すかログ確認を")

    # cad-khana (optional・HLR 線画用)
    if with_khana and not KHANA_MARKER.exists():
        log("khana: cad-khana を導入中 (optional)…", quiet)
        r = subprocess.run([uv(), "pip", "install", "--python", str(venv_python()),
                            KHANA_SPEC], capture_output=True, text=True)
        if r.returncode == 0:
            KHANA_MARKER.write_text("ok")
            log("khana: OK", quiet)
        else:
            log("khana: 導入失敗 (HLR 線画は無効。シェーディング描画は使えます)\n"
                f"      {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}", quiet)


def check_gl(quiet: bool):
    """シェーディング描画の GL バックエンドを検査して案内 (致命ではない)。"""
    py = venv_python()
    probe = (
        "import os, sys\n"
        "for be in ('egl','osmesa'):\n"
        "    os.environ['PYOPENGL_PLATFORM']=be\n"
        "    try:\n"
        "        import pyrender, numpy as np\n"
        "        r=pyrender.OffscreenRenderer(64,64)\n"
        "        s=pyrender.Scene()\n"
        "        r.render(s); r.delete()\n"
        "        print('GLOK '+be); sys.exit(0)\n"
        "    except Exception as e:\n"
        "        sys.stderr.write(be+': '+str(e)[:120]+'\\n')\n"
        "        for m in list(sys.modules):\n"
        "            if 'OpenGL' in m or 'pyrender' in m: sys.modules.pop(m,None)\n"
        "print('GLNONE')\n"
    )
    r = subprocess.run([str(py), "-c", probe], capture_output=True, text=True)
    out = (r.stdout or "").strip()
    if out.startswith("GLOK"):
        backend = out.split()[-1]
        log(f"gl: シェーディング描画 OK (backend={backend})", quiet)
        return backend
    log("gl: EGL/OSMesa いずれも不可。シェーディング描画は xvfb-run か HLR 線画にフォールバック。\n"
        "    必要なら: sudo apt install libgl1 libegl1 libosmesa6 xvfb", quiet)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--with-khana", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--check-gl", action="store_true", help="GL 検査のみ")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    if args.check_gl:
        check_gl(args.quiet)
        print(str(venv_python()))
        return 0

    # flock で同時構築を直列化 (worktree 並列対策)
    import fcntl
    with LOCKFILE.open("w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        build(args.rebuild, args.with_khana, args.quiet)
        check_gl(args.quiet)

    print(str(venv_python()))  # 最終行: 呼び出し側が venv python を拾う
    return 0


if __name__ == "__main__":
    sys.exit(main())
