#!/usr/bin/env python3
"""
.ato ソースから接続グラフを Mermaid graph に変換する。

対象: トップレベル module 内の
  - `name = new Type`  (インスタンス宣言)
  - `a ~ b`            (直接接続)
  - `a ~> b ~> c ...`  (bridge チェーン)

注意:
  - 完全な構文木は使わず正規表現でゆるくパース
  - 主目的は「コードに基づく見取り図」であり、配線レベルの厳密性は持たない
  - 詳細な信号レベルの確認は KiCad pcbnew で行う前提
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def strip_comments(src: str) -> str:
    src = re.sub(r"#.*", "", src)
    src = re.sub(r'"""(.|\n)*?"""', "", src)
    return src


def find_modules(src: str) -> list[tuple[str, str]]:
    """`module Foo:` 行をヘッダにして、インデント or 空行が続く範囲を body とする。

    正規表現の greedy 挙動で空行を跨げるかどうかを当てにせず、行単位で確実に拾う。
    """
    header_re = re.compile(r"^module\s+(\w+)\s*:\s*$")
    modules: list[tuple[str, str]] = []
    current: str | None = None
    body: list[str] = []
    for line in src.splitlines():
        m = header_re.match(line)
        if m:
            if current is not None:
                modules.append((current, "\n".join(body)))
            current = m.group(1)
            body = []
            continue
        if current is None:
            continue
        # 空行 or インデントされた行は同一 module の body
        if line == "" or line[0] in (" ", "\t"):
            body.append(line)
        else:
            # 非インデントの非空行 → module 終了
            modules.append((current, "\n".join(body)))
            current = None
            body = []
    if current is not None:
        modules.append((current, "\n".join(body)))
    return modules


def find_instances(body: str) -> list[tuple[str, str]]:
    return re.findall(
        r"^\s+([A-Za-z_]\w*)\s*=\s*new\s+([\w\.\[\]]+)", body, re.M
    )


def find_connections(body: str) -> list[list[str]]:
    out: list[list[str]] = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(
            ("module", "component", "import", "from", "#", "trait", '"""')
        ):
            continue
        if "~" not in s:
            continue
        if "=" in s and "==" not in s:
            continue
        s = s.rstrip(";")
        tokens = [t for t in re.split(r"\s*~>?\s*", s) if t]
        if len(tokens) >= 2:
            out.append(tokens)
    return out


def sanitize_id(name: str) -> str:
    return re.sub(r"[^\w]", "_", name)


def to_mermaid(path: Path, fenced: bool = True) -> str:
    src = strip_comments(path.read_text(encoding="utf-8"))
    lines: list[str] = []
    if fenced:
        lines.append("```mermaid")
    lines.append("graph LR")
    for mod, body in find_modules(src):
        instances = find_instances(body)
        if not instances:
            continue
        mod_id = sanitize_id(mod)
        lines.append(f"  subgraph {mod_id}[{mod}]")

        def node_id(local_name: str) -> str:
            # Mermaid の node ID はグラフ全体でグローバル。
            # 別 module に同名インスタンスがあっても衝突しないよう module 名を prefix する。
            return f"{mod_id}__{sanitize_id(local_name)}"

        for name, type_ in instances:
            short_type = type_.rsplit(".", 1)[-1]
            lines.append(f'    {node_id(name)}["{name}<br/>({short_type})"]')
        lines.append("  end")
        seen: set[tuple[str, str]] = set()
        for chain in find_connections(body):
            for a, b in zip(chain, chain[1:]):
                la = a.split(".")[0].split("[")[0]
                lb = b.split(".")[0].split("[")[0]
                if la == lb:
                    continue
                edge = (node_id(la), node_id(lb))
                if edge in seen:
                    continue
                seen.add(edge)
                lines.append(f"  {edge[0]} --> {edge[1]}")
    if fenced:
        lines.append("```")
    return "\n".join(lines)


def main() -> int:
    args = sys.argv[1:]
    fenced = True
    if "--raw" in args:
        fenced = False
        args.remove("--raw")
    if len(args) != 1:
        print("usage: ato_to_mermaid.py [--raw] <path-to-ato>", file=sys.stderr)
        return 2
    print(to_mermaid(Path(args[0]), fenced=fenced))
    return 0


if __name__ == "__main__":
    sys.exit(main())
