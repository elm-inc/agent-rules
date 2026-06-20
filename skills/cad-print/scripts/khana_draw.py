"""cad-khana の HLR 線画 (khana draw) への optional ブリッジ。

設計上 cad-khana は「唯一固有の HLR 正投影/等角 線画」に縮退して使う (vendored+pin 予定)。
現状 cad-khana は pre-alpha で現行 build123d/OCP と依存衝突し導入できないことがある。
その場合は **None を返して degradable** にする (シェーディング描画 render_shaded で視覚ループ継続)。

将来: cad-khana の draw 部分のみ vendoring してコミット pin する。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def available() -> bool:
    return importlib.util.find_spec("cad_khana") is not None


def draw(part_script: Path, out_dir: Path, views=None):
    """HLR 線画を生成。khana が無ければ None。"""
    if not available():
        return None
    try:
        # cad-khana の API は pre-alpha で流動的なため、薄く呼ぶだけに留める。
        # 実 vendoring 時に正式な draw 呼び出しへ差し替える。
        from cad_khana.cli import main as khana_main  # type: ignore
        args = ["draw", str(part_script), "--out", str(out_dir), "--format", "png"]
        if views:
            args += ["--view", ",".join(views)]
        khana_main(args)
        vdir = Path(out_dir) / "views"
        return {"line_art_dir": str(vdir)} if vdir.exists() else None
    except Exception:
        return None
