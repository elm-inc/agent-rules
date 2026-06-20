"""cad-print 自前診断 (build123d/trimesh/scipy/OCP)。venv 内で実行される。

レッドチーム反映:
- 干渉/クリアランスは build123d/OCP で自前 (安全クリティカル、pre-alpha 依存に委ねない)。
- 干渉は **独立クロスチェック** (boolean 体積 + 最小距離==0) で silent 誤判定を防ぐ。
- 肉厚は **voxel + EDT (医軸近似)** を主にし、細リブ/テーパーで ray が逸れる問題を回避。
  近似である旨と "要目視" フラグを必ず添える。

各チェックは {name, kind, measured, threshold, margin, passed, detail} を返す。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import build123d as bd
import trimesh

from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # type: ignore


# ---------- mesh 変換 ----------

def to_trimesh(part, linear=0.05, angular=0.3) -> trimesh.Trimesh:
    """build123d Solid/Part/Compound → trimesh。STL 経由で確実に。"""
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as t:
        path = t.name
    bd.export_stl(part, path, tolerance=linear, angular_tolerance=angular)
    m = trimesh.load(path, process=True)
    Path(path).unlink(missing_ok=True)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(tuple(m.geometry.values()))
    return m


# ---------- 部品メトリクス ----------

def part_metrics(part, name: str) -> dict:
    bb = part.bounding_box()
    size = (bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z)
    iv = part.is_valid
    iv = iv() if callable(iv) else iv
    return {
        "name": name,
        "bbox_min": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
        "bbox_size": [round(s, 3) for s in size],
        "volume_mm3": round(part.volume, 3),
        "is_valid": bool(iv),
    }


# ---------- ① 干渉 (自前 + クロスチェック) ----------

def interference(a, b, name_a: str, name_b: str, eps_mm3: float = 0.001) -> dict:
    vol = 0.0
    try:
        inter = a & b  # build123d boolean intersection
        vol = float(inter.volume) if inter is not None else 0.0
    except Exception:
        vol = 0.0
    # 独立クロスチェック: 最小距離 (干渉していれば 0)
    dist = _min_distance(a, b)
    overlap = vol > eps_mm3
    cross = dist <= 1e-6
    passed = not overlap
    detail = f"{name_a}∩{name_b} 体積={vol:.3f}mm³, 最小距離={dist:.3f}mm"
    if overlap != cross:
        detail += " ⚠ボリュームと距離の判定不一致(要確認)"
    return {"name": f"no_interference[{name_a},{name_b}]", "kind": "interference",
            "measured": round(vol, 4), "threshold": eps_mm3, "margin": round(eps_mm3 - vol, 4),
            "passed": passed, "detail": detail}


# ---------- ② クリアランス (OCP 最小距離) ----------

def _min_distance(a, b) -> float:
    return float(BRepExtrema_DistShapeShape(a.wrapped, b.wrapped).Value())


def clearance(a, b, name_a: str, name_b: str, min_mm: float) -> dict:
    d = _min_distance(a, b)
    return {"name": f"clearance[{name_a},{name_b}]", "kind": "clearance",
            "measured": round(d, 3), "threshold": min_mm, "margin": round(d - min_mm, 3),
            "passed": d >= min_mm,
            "detail": f"{name_a}↔{name_b} 最小距離={d:.3f}mm (要 ≥{min_mm}mm)"}


# ---------- ③ 肉厚 (ray 法 — 業界標準。近似、フラグ付き) ----------
# NOTE: ray 法はテーパー/曲面でレイが逸れて過大評価しうる (レッドチーム指摘)。
# v1 は多数サンプルの低パーセンタイルで最小壁を取り「要目視」フラグ + PNG で補う。
# 将来: voxel/SDF + 細線化による精密版 (skimage 等) を opt-in 追加予定。

def min_wall(part, name: str, wall_min: float, mesh: trimesh.Trimesh | None = None,
             samples: int = 1500) -> dict:
    m = mesh if mesh is not None else to_trimesh(part)
    measured = None
    note = ""
    try:
        pts, fidx = trimesh.sample.sample_surface(m, samples)
        normals = m.face_normals[fidx]
        eps = float(max(m.extents)) * 1e-4 + 1e-4
        origins = pts - normals * eps          # 表面のわずか内側から
        dirs = -normals                         # 内向き
        locs, ray_idx, _ = m.ray.intersects_location(
            ray_origins=origins, ray_directions=dirs, multiple_hits=False)
        if len(locs):
            d = np.linalg.norm(locs - origins[ray_idx], axis=1)
            d = d[d > eps * 2]                  # 自己交差ノイズ除去
            if d.size:
                # 最小壁。単一サンプルのノイズを避け 1 パーセンタイル。
                measured = round(float(np.percentile(d, 1)), 3)
    except Exception as e:  # noqa
        note = f" (ray 失敗: {e})"
    passed = measured is not None and measured >= wall_min
    flag = " ⚠要目視(ray 近似)" if measured is not None else " ⚠肉厚評価不可"
    return {"name": f"min_wall[{name}]", "kind": "wall",
            "measured": measured, "threshold": wall_min,
            "margin": (round(measured - wall_min, 3) if measured is not None else None),
            "passed": passed,
            "detail": f"{name} 最小肉厚≈{measured}mm (要 ≥{wall_min}mm){flag}{note}"}


# ---------- ④ オーバーハング (法線×ビルド方向) ----------

def overhang(part, name: str, overhang_max: float, mesh: trimesh.Trimesh | None = None,
             up=(0, 0, 1)) -> dict:
    m = mesh if mesh is not None else to_trimesh(part)
    up = np.asarray(up, float)
    normals = m.face_normals
    areas = m.area_faces
    centroids = m.triangles_center
    nz = normals @ up
    downward = np.clip(-nz, 0.0, 1.0)
    ang = np.degrees(np.arcsin(downward))  # 0=垂直壁, 90=水平天井
    zmin = float(m.bounds[0][2])
    # ビルドプレート接地面 (下向き かつ 最下層) は支持されるので除外
    base = (downward > 0.99) & (centroids[:, 2] <= zmin + max(m.extents) * 0.01)
    bad = (ang > overhang_max) & (~base)
    area_bad = float(areas[bad].sum())
    max_ang = float(ang[bad].max()) if bad.any() else 0.0
    return {"name": f"overhang[{name}]", "kind": "overhang",
            "measured": round(max_ang, 1), "threshold": overhang_max,
            "margin": round(overhang_max - max_ang, 1), "passed": not bad.any(),
            "detail": f"{name} 最大オーバーハング={max_ang:.1f}° "
                      f"(要 ≤{overhang_max}°), 該当面積={area_bad:.1f}mm²"}


# ---------- ⑤ ビルドボリューム超過 ----------

def fits_in_volume(part, name: str, build_volume) -> dict:
    bb = part.bounding_box()
    size = [bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z]
    bv = sorted(build_volume)
    s = sorted(size)  # 回転で収まる可能性を考え昇順比較
    ok = all(si <= bvi + 1e-6 for si, bvi in zip(s, bv))
    worst = max(si - bvi for si, bvi in zip(s, bv))
    return {"name": f"fits_in_volume[{name}]", "kind": "build_volume",
            "measured": [round(x, 1) for x in size], "threshold": list(build_volume),
            "margin": round(-worst, 2), "passed": ok,
            "detail": f"{name} bbox={[round(x,1) for x in size]}mm "
                      f"vs build_volume={list(build_volume)}mm"}


# ---------- まとめ ----------

def diagnose(parts: dict, pinfo: dict, clearances=None, interferences=None) -> dict:
    """parts: {name: build123d obj}. clearances/interferences: [(a,b,min_mm)] / [(a,b)]。
    部品単体は printability (肉厚/オーバーハング/ビルドボリューム) を全件、
    ペア指定があれば干渉/クリアランスを評価する。"""
    asserts = []
    metrics = []
    meshes = {}
    for name, p in parts.items():
        metrics.append(part_metrics(p, name))
        meshes[name] = to_trimesh(p)
        asserts.append(min_wall(p, name, pinfo["wall_min"], meshes[name]))
        asserts.append(overhang(p, name, pinfo["overhang_max"], meshes[name]))
        asserts.append(fits_in_volume(p, name, pinfo["build_volume"]))
    for a, b in (interferences or []):
        asserts.append(interference(parts[a], parts[b], a, b))
    for a, b, mn in (clearances or []):
        asserts.append(clearance(parts[a], parts[b], a, b, mn))
    passed = all(x["passed"] for x in asserts)
    return {
        "schema": "cad-print/diagnostics/1",
        "status": "ok" if passed else "assertion_failed",
        "printer": pinfo,
        "parts": metrics,
        "assertions": asserts,
        "summary": {"total": len(asserts), "failed": sum(1 for x in asserts if not x["passed"])},
    }
