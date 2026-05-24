#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "scikit-learn>=1.3",
# ]
# ///
"""brainstorm-divergence.py — `.test-brainstorm.md` の disagreement 自動検出

各モデルセクション (`## XXX が挙げた観点`) から観点を抽出し、TF-IDF + cosine
類似度で他モデルとの一致度を計算する。すべての他モデル観点と類似度 < threshold
な観点を「単独モデルだけが挙げた重要候補」として `## DIVERGENT POINTS` セクション
にまとめてファイル末尾に追記する。

Phase 8 試運転で format_duration の docstring/実装不一致を DeepSeek-R1 が単独で
発見した事例を機械的に拾えるようにする (AGENT-19)。

Usage:
    python3 brainstorm-divergence.py foo.test-brainstorm.md           # stdout
    python3 brainstorm-divergence.py foo.test-brainstorm.md --inplace # ファイル末尾追記
    python3 brainstorm-divergence.py foo.test-brainstorm.md --threshold 0.30
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 依存は冒頭の PEP 723 メタデータで uv が自動解決する
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def parse_brainstorm(text: str) -> dict[str, list[str]]:
    """Markdown を {モデル名: [観点テキスト...]} に分解する。

    `## XXX が挙げた観点` のヘッダを直接モデル境界として認識し、次の同パターン
    (または EOF) までを 1 モデル分の本文とする。本文内部の H2/H3 (DeepSeek-R1 が
    `## 正常系の典型ケース` を出力するなど) で分割されないようにする。

    箇条書き `- foo` / `* foo` / `- **観点N**: foo` を観点として収集し、`**` や
    バッククォートの装飾を剥がす。
    """
    pattern = re.compile(r"^##\s+(.+?)が挙げた観点", re.MULTILINE)
    matches = list(pattern.finditer(text))
    model_points: dict[str, list[str]] = {}
    for i, m in enumerate(matches):
        model = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        points: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("- ", "* ")):
                cleaned = re.sub(r"^[-*]\s+", "", stripped)
                cleaned = re.sub(r"\*\*([^*]+?)\*\*", r"\1", cleaned)
                cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
                cleaned = cleaned.strip()
                if len(cleaned) >= 5:
                    points.append(cleaned)
        if points:
            model_points[model] = points
    return model_points


def find_divergent(model_points: dict[str, list[str]], threshold: float) -> list[dict]:
    """各観点について他モデルとの最高 cosine 類似度を計算、threshold 未満を divergent とする。"""
    all_points: list[str] = []
    all_models: list[str] = []
    for model, points in model_points.items():
        for p in points:
            all_points.append(p)
            all_models.append(model)

    if len(all_points) < 2:
        return []

    # 日本語含む短文向けに char n-gram の TF-IDF を使う (sklearn 単独で動く)
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
    X = vectorizer.fit_transform(all_points)
    sim = cosine_similarity(X)

    divergent: list[dict] = []
    for i, (point, model) in enumerate(zip(all_points, all_models)):
        other_idx = [j for j, m in enumerate(all_models) if m != model]
        if not other_idx:
            continue
        max_sim = max(float(sim[i, j]) for j in other_idx)
        if max_sim < threshold:
            divergent.append({"model": model, "point": point, "max_sim": max_sim})
    return divergent


def render_section(divergent: list[dict], threshold: float, total: int) -> str:
    if not divergent:
        return (
            f"\n\n## DIVERGENT POINTS (閾値 {threshold:.2f})\n\n"
            f"_モデル間で観点が概ね一致しています ({total} 観点中、divergent 0 件)。_\n"
        )

    lines = [
        f"\n\n## DIVERGENT POINTS (閾値 {threshold:.2f})\n",
        f"以下の **{len(divergent)} 件 / 総 {total} 観点** は、特定モデルだけが挙げた他モデルと類似度の低い観点です。",
        "**単独モデルなら見落としていたが多モデル化で拾えた重要候補**の可能性が高いので、人間がレビューしてください。",
        "(Phase 8 試運転では DeepSeek-R1 単独の観点 49「実装と docstring の不一致」がここに該当しました)\n",
    ]
    by_model: dict[str, list[dict]] = {}
    for d in divergent:
        by_model.setdefault(d["model"], []).append(d)
    for model, items in by_model.items():
        lines.append(f"### {model} の単独観点 ({len(items)} 件)")
        for d in sorted(items, key=lambda x: x["max_sim"]):
            lines.append(f"- (類似度 {d['max_sim']:.2f}) {d['point']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help=".test-brainstorm.md のパス")
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="cosine 類似度の divergent 閾値 (default: 0.35)。下げるほど多く分類される",
    )
    ap.add_argument(
        "--inplace",
        action="store_true",
        help="DIVERGENT POINTS セクションを入力ファイル末尾に書き込む (既存セクションは置換)",
    )
    args = ap.parse_args()

    path = Path(args.file)
    text = path.read_text(encoding="utf-8")

    # 既存の DIVERGENT POINTS を除去して重複追記を防ぐ
    text = re.sub(
        r"\n\n## DIVERGENT POINTS.*?(?=\n\n## (?!DIVERGENT)|\Z)",
        "",
        text,
        flags=re.DOTALL,
    )

    model_points = parse_brainstorm(text)
    if len(model_points) < 2:
        sys.exit(
            f"error: 2 モデル以上の '## ... が挙げた観点' セクションが必要です "
            f"(見つかった: {list(model_points.keys())})"
        )

    total = sum(len(v) for v in model_points.values())
    divergent = find_divergent(model_points, args.threshold)
    section = render_section(divergent, args.threshold, total)

    if args.inplace:
        path.write_text(text + section, encoding="utf-8")
        print(f"updated: {path}", file=sys.stderr)
        print(f"models: {list(model_points.keys())}", file=sys.stderr)
        print(f"total points: {total}, divergent: {len(divergent)}", file=sys.stderr)
    else:
        print(text + section)


if __name__ == "__main__":
    main()
