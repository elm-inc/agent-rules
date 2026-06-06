#!/usr/bin/env python3
"""ai_smell_lint — 生成 UI/スライド成果物から「AIっぽさ」(tell) を静的検出する。

design-voice skill の critic モード(機械パート)。依存ライブラリなし(標準ライブラリのみ)。
検出するのは機械的に拾える tell (配色・書体・装飾・絵文字・常套句) のみ。
レイアウトの単調さ・コピーの抑揚などは LLM judge が担当する(SKILL.md 参照)。

使い方:
    python3 ai_smell_lint.py <target> [--profile tokens.json] [--threshold N] [--json]

<target> はファイル or ディレクトリ。ディレクトリは対象拡張子を再帰走査。
exit code: AI臭スコア < threshold なら 0、それ以上なら 1(critic ループ / CI のゲート用)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCAN_EXT = {
    ".css", ".scss", ".html", ".htm", ".jsx", ".tsx",
    ".js", ".ts", ".vue", ".svelte", ".astro", ".md", ".mdx",
}

# 絵文字レンジ(アイコン代用の検出用)。装飾記号系も含める。
EMOJI = (
    "[\U0001F300-\U0001FAFF\U0001F000-\U0001F02F"
    "\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF\U0000FE0F]"
)

# (category, weight, compiled regex, human message)
# weight は AI臭スコアへの寄与。median 回帰の強い tell ほど高い。
RULES: list[tuple[str, int, re.Pattern, str]] = [
    ("palette", 8, re.compile(
        r"(from-(blue|indigo|violet|purple)-\d{2,3}\s+(via-\w+-\d{2,3}\s+)?to-(purple|violet|fuchsia|indigo|pink)-\d{2,3})",
        re.I), "青→紫 グラデーション (Tailwind utility)"),
    ("palette", 8, re.compile(
        r"linear-gradient\([^)]*#(6366f1|818cf8|8b5cf6|a855f7|7c3aed|6d28d9|c084fc)", re.I),
        "青→紫 グラデーション (CSS, indigo/violet hex)"),
    ("palette", 4, re.compile(
        r"#(6366f1|818cf8|8b5cf6|a855f7|7c3aed|6d28d9)\b", re.I),
        "indigo/violet 既定アクセント hex"),
    ("typography", 6, re.compile(
        r"font-family\s*:\s*[\"']?Inter\b", re.I), "Inter を font-family 既定に"),
    ("typography", 5, re.compile(
        r"font-(sans|family)[^;{}\n]*\bsystem-ui\b", re.I),
        "system-ui を無検討で既定に"),
    ("decoration", 7, re.compile(
        r"\bbackdrop-blur\b|backdrop-filter\s*:\s*blur", re.I),
        "glassmorphism (backdrop-blur)"),
    ("decoration", 4, re.compile(
        r"\brounded-(xl|2xl)\b[^\"'>]*\bshadow-(sm|md)\b|\bshadow-(sm|md)\b[^\"'>]*\brounded-(xl|2xl)\b",
        re.I), "汎用 角丸+薄影カード"),
    ("motion", 3, re.compile(
        r"\btransition-all\b[^\"'>]*\bduration-300\b|\bduration-300\b[^\"'>]*\bease-in-out\b", re.I),
        "無設計トランジション (transition-all duration-300)"),
    ("layout", 3, re.compile(
        r"\bmax-w-7xl\b[^\"'>]*\bmx-auto\b", re.I),
        "max-w-7xl mx-auto 既定コンテナ"),
    ("copy", 3, re.compile(
        r"\b(seamlessly|effortlessly|supercharge|unlock your|elevate your|take .* to the next level|game-?changer)\b",
        re.I), "AI 常套句コピー"),
]

EMOJI_ICON = re.compile(
    r"(>\s*" + EMOJI + r")|(\b(title|heading|label)\b[^\n]{0,40}" + EMOJI + r")|"
    r"(^[\s>*-]*" + EMOJI + r")", re.I | re.M)


def build_profile_rules(profile_path: Path):
    """tokens.json の forbid を読み、プロファイル固有の追加 lint ルールを生成する。

    forbid の値(文字列)をキーワード照合し、対応する検出ルールを足す。
    これにより editorial-mono の「any background gradient」「centered hero」等、
    プロファイル DNA 固有の禁止事項を機械検出に反映できる。
    """
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    forbid = data.get("forbid", {})
    blob = " ".join(
        str(v).lower()
        for vals in forbid.values()
        for v in (vals if isinstance(vals, list) else [vals])
    )
    rules = []
    if "gradient" in blob:  # 色を問わず全グラデーション禁止
        rules.append(("palette", 6, re.compile(
            r"(linear|radial|conic)-gradient\(|\bbg-gradient-to-[a-z]+\b", re.I),
            "プロファイル禁止: 背景グラデーション全般"))
    if "center" in blob:  # 中央寄せヒーロー禁止
        rules.append(("layout", 5, re.compile(
            r"text-align\s*:\s*center|\btext-center\b", re.I),
            "プロファイル禁止: 中央寄せ(centered hero)"))
    if "shadow" in blob:  # 面のドロップシャドウ禁止
        rules.append(("decoration", 4, re.compile(
            r"box-shadow\s*:\s*(?!none)|\bshadow-(sm|md|lg|xl|2xl)\b", re.I),
            "プロファイル禁止: 面のドロップシャドウ"))
    return rules


def scan_text(text: str, extra_rules=()):
    findings = []
    lines = text.splitlines()
    for cat, weight, rx, msg in list(RULES) + list(extra_rules):
        for m in rx.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            findings.append((cat, weight, line_no, msg, lines[line_no - 1].strip()[:100]))
    # 絵文字アイコン代用
    for m in EMOJI_ICON.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        findings.append(("iconography", 5, line_no, "絵文字をアイコン代用",
                         lines[line_no - 1].strip()[:100]))
    return findings


EXCLUDE_DIRS = {"node_modules", ".git", "dist", "build", ".next"}


def iter_files(target: Path):
    if target.is_file():
        yield target
        return
    for p in sorted(target.rglob("*")):
        if p.is_file() and p.suffix.lower() in SCAN_EXT:
            # 依存/ビルド成果物は除外。ただし target 自身がその名前でも、
            # target 直下(=明示指定された対象)は除外しない。除外は target より
            # 下のネストしたディレクトリ名のみに適用する。
            rel_dirs = p.relative_to(target).parts[:-1]
            if any(part in EXCLUDE_DIRS for part in rel_dirs):
                continue
            yield p


def main() -> int:
    ap = argparse.ArgumentParser(description="design-voice の AI臭 lint")
    ap.add_argument("target", help="検査するファイル or ディレクトリ")
    ap.add_argument("--profile", help="プロファイルの tokens.json (forbid 強化 / 任意)")
    ap.add_argument("--threshold", type=int, default=30, help="この値以上で exit 1 (既定 30)")
    ap.add_argument("--json", action="store_true", help="JSON 出力")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"ERROR: 対象が存在しません: {target}", file=sys.stderr)
        return 2

    extra_rules = ()
    if args.profile:
        profile_path = Path(args.profile)
        if not profile_path.is_file():
            print(f"ERROR: --profile が見つかりません: {profile_path}", file=sys.stderr)
            return 2
        try:
            extra_rules = build_profile_rules(profile_path)
        except (json.JSONDecodeError, OSError) as e:
            print(f"ERROR: --profile を読めません ({profile_path}): {e}", file=sys.stderr)
            return 2

    all_findings = []
    for f in iter_files(target):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for cat, weight, line_no, msg, ctx in scan_text(text, extra_rules):
            all_findings.append({
                "file": str(f), "line": line_no, "category": cat,
                "weight": weight, "message": msg, "context": ctx,
            })

    score = min(100, sum(x["weight"] for x in all_findings))
    by_cat: dict[str, int] = {}
    for x in all_findings:
        by_cat[x["category"]] = by_cat.get(x["category"], 0) + 1

    if args.json:
        print(json.dumps({
            "score": score, "threshold": args.threshold,
            "by_category": by_cat, "findings": all_findings,
        }, ensure_ascii=False, indent=2))
    else:
        if not all_findings:
            print("✓ AI臭 tell は検出されませんでした (機械パート)。スコア 0")
        else:
            print(f"AI臭スコア(機械パート): {score} / threshold {args.threshold}")
            print(f"カテゴリ別: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
            print("-" * 60)
            for x in all_findings:
                print(f"  [{x['category']:11}] {x['file']}:{x['line']}  {x['message']}")
                if x["context"]:
                    print(f"               {x['context']}")
        print()
        print("注: レイアウトの単調さ・コピーの抑揚・モーション設計は LLM judge で別途評価してください。")

    return 1 if score >= args.threshold else 0


if __name__ == "__main__":
    sys.exit(main())
