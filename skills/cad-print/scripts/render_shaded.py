"""シェーディング多視点 PNG レンダラ。venv 内で実行。

バックエンド選択 (レッドチーム反映の GL フォールバック):
  1. pyrender + EGL (GPU)
  2. pyrender + OSMesa (CPU ソフトウェア)
  3. matplotlib trisurf (GL 不要・純 CPU) ← GL が一切無い環境でも必ず動く確実経路
(さらに HLR 線画フォールバックは khana_draw.py が別途担当)

AI がマルチモーダルに「形の妥当性」を見るのが目的。寸法確認は線画/診断 JSON で補う。
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import trimesh

# 既定の視点 (elev, azim) — iso + 三面
VIEWS = {
    "iso": (28, -55),
    "front": (0, -90),
    "top": (90, -90),
    "right": (0, 0),
}


def _as_mesh(obj) -> trimesh.Trimesh:
    if isinstance(obj, trimesh.Trimesh):
        return obj
    from diagnostics import to_trimesh  # build123d → trimesh
    return to_trimesh(obj)


# ---------- pyrender (GL) ----------

def _try_pyrender(mesh, out_dir, views, size) -> list | None:
    for backend in ("egl", "osmesa"):
        os.environ["PYOPENGL_PLATFORM"] = backend
        try:
            import pyrender  # noqa
            scene = pyrender.Scene(bg_color=[1, 1, 1, 1], ambient_light=[0.3, 0.3, 0.3])
            mesh_pr = pyrender.Mesh.from_trimesh(mesh, smooth=False)
            scene.add(mesh_pr)
            r = pyrender.OffscreenRenderer(size, size)
            b = mesh.bounds
            ctr = b.mean(axis=0)
            rad = float(np.linalg.norm(b[1] - b[0])) / 2 or 1.0
            out = []
            cam = pyrender.PerspectiveCamera(yfov=np.pi / 4.0)
            light = pyrender.DirectionalLight(color=[1, 1, 1], intensity=3.0)
            for name, (elev, azim) in views.items():
                pose = _cam_pose(ctr, rad, elev, azim)
                cn = scene.add(cam, pose=pose)
                ln = scene.add(light, pose=pose)
                color, _ = r.render(scene)
                from PIL import Image
                p = Path(out_dir) / f"{name}.png"
                Image.fromarray(color).save(p)
                out.append((name, str(p)))
                scene.remove_node(cn)
                scene.remove_node(ln)
            r.delete()
            return out
        except Exception:
            for m in list(__import__("sys").modules):
                if "OpenGL" in m or "pyrender" in m:
                    __import__("sys").modules.pop(m, None)
            continue
    return None


def _cam_pose(center, radius, elev_deg, azim_deg):
    e = np.radians(elev_deg)
    a = np.radians(azim_deg)
    d = radius * 3.0
    eye = center + d * np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    fwd = (center - eye)
    fwd /= np.linalg.norm(fwd)
    up = np.array([0, 0, 1.0])
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right) or 1
    up2 = np.cross(right, fwd)
    pose = np.eye(4)
    pose[:3, 0] = right
    pose[:3, 1] = up2
    pose[:3, 2] = -fwd
    pose[:3, 3] = eye
    return pose


# ---------- matplotlib (GL 不要フォールバック) ----------

def _shade_colors(mesh, light=(-0.3, -0.5, 0.85)):
    n = mesh.face_normals
    l = np.asarray(light, float)
    l /= np.linalg.norm(l)
    inten = np.clip(n @ l, 0, 1) * 0.72 + 0.28
    base = np.array([0.62, 0.66, 0.74])  # 青みグレー (median 回避の薄い個性)
    return np.clip(inten[:, None] * base, 0, 1)


def _try_matplotlib(mesh, out_dir, views, size) -> list:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    tris = mesh.vertices[mesh.faces]
    colors = _shade_colors(mesh)
    b = mesh.bounds
    ctr = b.mean(axis=0)
    rad = float((b[1] - b[0]).max()) / 2 * 1.08 or 1.0
    out = []
    for name, (elev, azim) in views.items():
        fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        pc = Poly3DCollection(tris, facecolors=colors, edgecolors="none", linewidths=0)
        ax.add_collection3d(pc)
        ax.set_xlim(ctr[0] - rad, ctr[0] + rad)
        ax.set_ylim(ctr[1] - rad, ctr[1] + rad)
        ax.set_zlim(ctr[2] - rad, ctr[2] + rad)
        try:
            ax.set_box_aspect((1, 1, 1))
        except Exception:
            pass
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        p = Path(out_dir) / f"{name}.png"
        fig.savefig(p, bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
        out.append((name, str(p)))
    return out


# ---------- entry ----------

def render(obj, out_dir, views=None, size=720, backend="auto") -> dict:
    """既定 (auto) は matplotlib trisurf — GL 不要で確実、凹凸/挿入も正しく見える。
    pyrender は backend='pyrender' で明示選択 (高品質だがカメラ調整が要・GL 必須)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh = _as_mesh(obj)
    views = views or VIEWS
    used = None
    files = None
    if backend in ("pyrender", "gl"):
        files = _try_pyrender(mesh, out_dir, views, size)
        used = "pyrender" if files else None
    if files is None:
        files = _try_matplotlib(mesh, out_dir, views, size)
        used = "matplotlib"
    return {"backend": used, "views": dict(files)}


if __name__ == "__main__":
    import argparse
    import build123d as bd  # noqa

    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", default="figma-export")
    a = ap.parse_args()
    if a.demo:
        part = bd.Box(20, 20, 20) - bd.Box(16, 16, 22)
        print(render(part, a.out))
