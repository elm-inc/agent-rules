#!/usr/bin/env python3
"""業務フロー図 (Mermaid) の標準準拠バリデータ (agent-rules)。

書式の一貫性と必須情報の網羅を機械保証する。標準: docs/design/flow-diagram-standard.md /
根拠: docs/adr/0015-business-flow-diagram-standard.md。

使い方:
    lint-flow-diagram.py <file.flow.md> [<file2.flow.md> ...]
    lint-flow-diagram.py --glob 'docs/**/*.flow.md'

規約違反 (errors) があれば exit 1。warnings は exit に影響しない。
Mermaid の完全パーサではなく、標準準拠のための構造 lint (正規表現ベース)。
"""
from __future__ import annotations
import argparse
import glob as globmod
import re
import sys

REQUIRED_FM = ["process", "purpose", "owner", "actors", "systems", "trigger", "version", "updated"]
LIST_FM = ["actors", "systems"]
# ノード宣言: id の直後に来る形状開き括弧 (長いものから先に判定する)
SHAPE_OPENERS = [r"\(\[", r"\[\(", r"\[/", r"\{", r"\["]  # ([  [(  [/  {  [
NODE_DECL_RE = re.compile(r"(?:^|[\s>|])([A-Za-z0-9_]+)(" + "|".join(SHAPE_OPENERS) + r")")
EDGE_RE = re.compile(r"([A-Za-z0-9_]+)\s*(-->|---|-\.->|==>|-\.-)\s*(\|[^|]*\|)?\s*([A-Za-z0-9_]+)")


def parse_frontmatter(text: str):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    body = text[m.end():]
    fm: dict = {}
    key = None
    for line in m.group(1).splitlines():
        mkv = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$", line)
        if mkv:
            k, v = mkv.group(1), mkv.group(2).strip()
            if v == "":
                fm[k] = []
                key = k
            else:
                fm[k] = v
                key = None
        elif re.match(r"^\s*-\s+", line) and key is not None:
            fm[key].append(re.sub(r"^\s*-\s+", "", line).strip())
        elif line.strip() == "":
            key = None
    return fm, body


def extract_mermaid(body: str):
    m = re.search(r"```mermaid\s*\n(.*?)```", body, re.S)
    return m.group(1) if m else None


def check(path: str) -> tuple[list, list]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return [f"ファイルを開けない: {e}"], []

    fm, body = parse_frontmatter(text)
    if fm is None:
        errors.append("frontmatter (--- ... ---) が無い")
        fm = {}
    else:
        for field in REQUIRED_FM:
            val = fm.get(field)
            if val is None or (isinstance(val, str) and not val) or (isinstance(val, list) and not val):
                errors.append(f"frontmatter 必須欄が未記入: {field}")
        for lf in LIST_FM:
            if lf in fm and not isinstance(fm[lf], list):
                errors.append(f"{lf} はリスト (- item) で記載する")

    mer = extract_mermaid(body) if body else None
    if not mer:
        errors.append("```mermaid ブロックが無い")
        return errors, warnings

    if not re.search(r"\bflowchart\s+TD\b", mer):
        errors.append("Mermaid は `flowchart TD` で始める (方向 TD 固定)")

    # 開始/終了ノード (stadium ([...]))。形状は元テキストから検出する。
    stadium = set(re.findall(r"([A-Za-z0-9_]+)\(\[", mer))
    if len(stadium) < 2:
        errors.append("開始/終了ノード ([...]) が 2 つ未満 — 開始と全終了状態を明示する")

    # エッジ解析用に形状本体と :::class を剥がした正規化版を作る
    # (インライン宣言 `S([...]) --> A[...]` から素の id を取り出すため)。長い形状から順に除去。
    flat = mer
    for pat in (r"\(\[.*?\]\)", r"\[\(.*?\)\]", r"\[/.*?/\]", r"\{.*?\}", r"\[.*?\]", r":::\w+"):
        flat = re.sub(pat, "", flat)

    # エッジ (正規化版から)
    edges = EDGE_RE.findall(flat)

    # 判断ノード ({...}) は 分岐 >=2 かつ全て条件ラベル付き
    decisions = set(re.findall(r"([A-Za-z0-9_]+)\{", mer))
    for d in sorted(decisions):
        outs = [e for e in edges if e[0] == d]
        if len(outs) < 2:
            errors.append(f"判断ノード {d} の分岐が 2 本未満 (条件で分けること)")
        if any(not e[2] for e in outs):
            errors.append(f"判断ノード {d} の分岐に条件ラベル (-->|...|) が無いものがある")

    # swimlane (subgraph) とアクター網羅
    subgraphs = re.findall(r"subgraph\s+\"?([^\"\n]+?)\"?\s*$", mer, re.M)
    for a in fm.get("actors", []) if isinstance(fm.get("actors"), list) else []:
        if not any(a in sg for sg in subgraphs):
            warnings.append(f"アクター '{a}' の swimlane (subgraph) が見当たらない")
    if not subgraphs:
        warnings.append("subgraph (swimlane) が 1 つも無い — アクター別レーンを推奨")

    # 例外経路: classDef exception を定義し、いずれかのノードに適用
    has_exc_def = re.search(r"classDef\s+exception\b", mer)
    has_exc_use = re.search(r":::exception\b", mer) or re.search(r"class\s+[\w, ]+\bexception\b", mer)
    if not (has_exc_def and has_exc_use):
        errors.append("例外経路が無い — classDef exception を定義し、例外ノード/終了に適用する")

    # 孤立ノード (宣言されたがエッジに現れない)
    declared = set(m.group(1) for m in NODE_DECL_RE.finditer(mer))
    in_edges = set()
    for e in edges:
        in_edges.add(e[0])
        in_edges.add(e[3])
    for o in sorted(declared - in_edges):
        errors.append(f"孤立ノード (エッジ未接続): {o}")

    # 未定義 classDef 参照
    defined = set(re.findall(r"classDef\s+(\w+)", mer))
    used = set(re.findall(r":::(\w+)", mer))
    for m2 in re.findall(r"class\s+([\w, ]+?)\s+(\w+)\s*$", mer, re.M):
        used.add(m2[1])
    for u in sorted(used - defined):
        errors.append(f"未定義の classDef 参照: {u}")

    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="業務フロー図 (Mermaid) 標準準拠 lint")
    ap.add_argument("files", nargs="*", help="対象 .flow.md")
    ap.add_argument("--glob", help="glob パターンで対象を指定")
    args = ap.parse_args()

    targets = list(args.files)
    if args.glob:
        targets += globmod.glob(args.glob, recursive=True)
    if not targets:
        print("対象ファイルが無い", file=sys.stderr)
        return 2

    total_err = 0
    for path in targets:
        errors, warnings = check(path)
        if errors or warnings:
            print(f"=== {path} ===")
        for w in warnings:
            print(f"  WARN: {w}")
        for e in errors:
            print(f"  FAIL: {e}")
        if not errors:
            print(f"ok:   {path}" + (f" (WARN {len(warnings)})" if warnings else ""))
        total_err += len(errors)

    if total_err:
        print(f"\nflow-lint: FAIL ({total_err} 件)")
        return 1
    print("\nflow-lint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
