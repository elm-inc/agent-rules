"""cad-print 嵌合較正ヘルパ。build123d モデル (part.py) が import して使う。

設計上の約束 (符号と適用先を曖昧にしない — レッドチーム反映):
  較正値 `clearance/sliding/friction` = **ラジアル(片側)ギャップ [mm]**。
  `press` = 負値 = 片側干渉量 (圧入)。
  これらは「設計上の理想隙間」ではなく、その嵌合を実機で得るための経験オフセット。

  hole(nominal, fit) = nominal + 2*gap   # 穴を両側に広げる(相手ペグは nominal 想定)
  peg (nominal, fit) = nominal - 2*gap   # 代わりにペグを縮める(穴を動かせない時)
  gap (fit)          = gap               # 片側ギャップのスカラ(リブ/蓋の単側隙間)
  press は gap が負なので、hole("press")=穴縮め / peg("press")=ペグ太らせ で干渉になる。

  elephant_foot は径に混ぜず chamfer 値として別取得 (elephant_foot_chamfer)。
  高温材の収縮は shrink_scale() を全体寸法に掛けて補正。

プリンタ/素材の解決順:
  set_context() > 環境変数 CAD_PRINT_PRINTER / CAD_PRINT_MATERIAL > calibration.toml の default_*
較正ファイルの解決順:
  CAD_PRINT_CALIBRATION > ./calibration.toml (cwd) > skills/cad-print/templates/calibration.toml
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

_DEFAULT_TOML = Path(__file__).resolve().parent.parent / "templates" / "calibration.toml"

_ctx = {"printer": None, "material": None}


def set_context(printer: str | None = None, material: str | None = None):
    """テストや明示指定用。part.py から呼んでもよい。"""
    if printer:
        _ctx["printer"] = printer
    if material:
        _ctx["material"] = material
    _resolve.cache_clear()


def _calibration_path() -> Path:
    env = os.environ.get("CAD_PRINT_CALIBRATION")
    if env:
        return Path(env)
    cwd = Path.cwd() / "calibration.toml"
    if cwd.exists():
        return cwd
    return _DEFAULT_TOML


@lru_cache(maxsize=1)
def _load() -> dict:
    p = _calibration_path()
    if not p.exists():
        raise FileNotFoundError(f"calibration.toml が見つかりません: {p}")
    with p.open("rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=8)
def _resolve() -> tuple[str, str, dict, dict]:
    cal = _load()
    printer = _ctx["printer"] or os.environ.get("CAD_PRINT_PRINTER") or cal.get("default_printer")
    material = _ctx["material"] or os.environ.get("CAD_PRINT_MATERIAL") or cal.get("default_material")
    printers = cal.get("printer", {})
    if printer not in printers:
        raise KeyError(f"未知のプリンタ '{printer}'。calibration.toml の [printer.*]: "
                       f"{list(printers)}")
    pblock = printers[printer]
    if material not in pblock:
        avail = [k for k, v in pblock.items() if isinstance(v, dict)]
        raise KeyError(f"プリンタ '{printer}' に素材 '{material}' の較正がありません。利用可: {avail}")
    return printer, material, pblock, pblock[material]


def _mat() -> dict:
    return _resolve()[3]


def _pinfo() -> dict:
    return _resolve()[2]


def fit_value(name: str, axis: str | None = None) -> float:
    """較正値(片側ギャップ)を返す。値がテーブル {xy,z} なら axis で選択。"""
    m = _mat()
    if name not in m:
        raise KeyError(f"fit '{name}' が素材較正に無い。利用可: "
                       f"{[k for k in m if k in ('clearance','sliding','friction','press')]}")
    v = m[name]
    if isinstance(v, dict):  # 軸別
        key = (axis or "xy").lower()
        if key not in v:
            key = "xy" if "xy" in v else next(iter(v))
        return float(v[key])
    return float(v)


def hole(nominal: float, fit: str = "clearance", axis: str | None = None) -> float:
    """嵌合穴の直径。穴を両側に広げる (相手ペグ径 = nominal 想定)。"""
    return nominal + 2.0 * fit_value(fit, axis)


def peg(nominal: float, fit: str = "clearance", axis: str | None = None) -> float:
    """嵌合ペグ/軸の直径。穴を動かせない時にペグ側を縮める。"""
    return nominal - 2.0 * fit_value(fit, axis)


def gap(fit: str = "sliding", axis: str | None = None) -> float:
    """片側ギャップのスカラ。蓋のリム・スロット等の単側隙間に。"""
    return fit_value(fit, axis)


def elephant_foot_chamfer() -> float:
    """底面に推奨する面取り量 [mm@45deg]。0 なら不要。"""
    return float(_mat().get("elephant_foot_chamfer", 0.0))


def shrink_scale() -> float:
    """高温材の収縮補正スケール (全体寸法に掛ける)。収縮 0.6% なら ~1.006。"""
    return 1.0 + float(_mat().get("shrink_comp", 0.0))


def nozzle() -> float:
    return float(_pinfo().get("nozzle", 0.4))


def wall_min() -> float:
    """推奨最小肉厚 [mm]。素材較正に wall_min があればそれ、無ければ 2*nozzle と 0.8 の大。"""
    m = _mat()
    if "wall_min" in m:
        return float(m["wall_min"])
    return max(0.8, 2.0 * nozzle())


def overhang_max() -> float:
    """サポート無しで許容する最大オーバーハング角 [deg]。"""
    return float(_mat().get("overhang_max", 45.0))


def build_volume(dual: bool = False) -> tuple[float, float, float]:
    p = _pinfo()
    key = "build_volume_dual" if (dual and "build_volume_dual" in p) else "build_volume"
    bv = p.get(key, [256, 256, 256])
    return (float(bv[0]), float(bv[1]), float(bv[2]))


def printer_info() -> dict:
    printer, material, pinfo, mat = _resolve()
    return {
        "printer": printer, "material": material,
        "nozzle": nozzle(), "enclosed": bool(pinfo.get("enclosed", False)),
        "extruders": int(pinfo.get("extruders", 1)),
        "build_volume": list(build_volume()),
        "wall_min": wall_min(), "overhang_max": overhang_max(),
        "elephant_foot_chamfer": elephant_foot_chamfer(), "shrink_scale": shrink_scale(),
    }


__all__ = ["set_context", "fit_value", "hole", "peg", "gap", "elephant_foot_chamfer",
           "shrink_scale", "nozzle", "wall_min", "overhang_max", "build_volume",
           "printer_info"]
