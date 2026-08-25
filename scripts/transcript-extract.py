#!/usr/bin/env python3
"""Claude Code の transcript から「人間が実際に書いた文」を取り出す。

/devlog の各モード (retro / playbook / excerpt / teach) が共通で使う抽出器。
手打ちの jq だと、スキル展開・コマンド出力・system-reminder が人間の発話に
混ざり、AskUserQuestion の質問と回答の対応付けも壊れやすいので、ここに寄せる。

機密 (最重要): **現プロジェクトの transcript だけを読む** (fail-closed)。
~/.claude/projects 全体を走査して最新を掴むような横断フォールバックは
実装しない — 別案件 = 顧客の会話を誤って読むため (ADR-0016)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECTS_ROOT = Path(
    os.environ.get("CLAUDE_PROJECTS_ROOT", Path.home() / ".claude/projects")
)

# 読めなかった理由。黙って「0 件」と見せないために集める (fail-closed)
SOURCE_WARNINGS: list[str] = []

# 人間の発話に混ざる「人間が書いていないもの」
SKILL_EXPANSION = "Base directory for this skill:"
COMMAND_MARKERS = ("<local-command", "<command-name>", "<command-message>")
SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
CAVEAT_RE = re.compile(r"<[a-z-]*caveat>.*?</[a-z-]*caveat>", re.S)
INTERRUPT = "[Request interrupted by user]"

# AskUserQuestion の結果 (tool_result 側に "質問"="回答" の形で入る)
ANSWER_PREFIXES = ("Your questions have been answered:", "The user answered:")
QA_PAIR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"')


@dataclass
class Turn:
    index: int
    timestamp: str
    text: str
    kind: str  # human | interrupt


@dataclass
class Choice:
    question: str
    answer: str


# --------------------------------------------------------------------------
# transcript の特定 (現プロジェクト限定・fail-closed)
# --------------------------------------------------------------------------


def git_path(flag: str) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", flag],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def allowed_roots() -> list[Path]:
    """transcript を探してよいルートの集合 (= すべて同じリポジトリ = 同じ案件)。

    セッションの起動 cwd によって transcript のディレクトリ名が変わるため、
    「現在の worktree」と「メインワークツリー」の両方を候補にする。
    どちらも同一リポジトリなので、案件をまたがない。
    """
    roots: list[Path] = []

    def add(p: Path | None) -> None:
        if p and p.is_dir() and p not in roots:
            roots.append(p)

    add(Path.cwd())
    add(git_path("--show-toplevel"))
    common = git_path("--git-common-dir")
    if common is not None and common.name == ".git":
        add(common.parent)  # worktree から見たメインワークツリー
    return roots


def resolve_root(explicit: str | None) -> tuple[Path, list[Path]]:
    """(主たるルート, 探索してよいルート一覧) を返す。

    `--project` は **同じリポジトリ内に限る** (fail-closed)。任意のパスを
    受けると「現プロジェクトだけ」という契約が引数ひとつで破れ、別案件 =
    顧客の会話を読んでしまう。cwd ずれの救済という本来の用途は、
    allowed_roots() が worktree とメインの両方を候補にすることで満たす。
    """
    roots = allowed_roots()
    if not explicit:
        return (roots[0] if roots else Path.cwd()), roots

    target = Path(explicit).resolve()
    if target not in [r.resolve() for r in roots]:
        sys.exit(
            f"ERROR: --project に指定できるのは現在のリポジトリだけです (fail-closed)\n"
            f"  指定された : {target}\n"
            f"  許可される : {', '.join(str(r) for r in roots) or '(なし)'}\n"
            f"  別プロジェクトの transcript は読みません (別案件=顧客の会話のため)。\n"
            f"  そのプロジェクトの学びを残したいなら、そのディレクトリで実行してください。"
        )
    return target, [target]


def encode_project(root: Path) -> str:
    """Claude Code の projects ディレクトリ名の規則 ('/' と '.' を '-' に)。"""
    return re.sub(r"[/.]", "-", str(root))


def project_dir(root: Path) -> Path:
    return PROJECTS_ROOT / encode_project(root)


def find_transcripts(root: Path) -> list[Path]:
    """現プロジェクトの jsonl を新しい順で返す。

    見つからなくても他プロジェクトを探しに行かない。ここで空を返し、
    呼び出し側がユーザーに確認する (fail-closed)。

    **symlink は拒否する**: ディレクトリや jsonl が symlink だと、現プロジェクトの
    パスを表示したまま別案件の transcript を読んでしまい、fail-closed の保証が
    静かに破れる (表示は正しいので気づけない)。
    """
    d = project_dir(root)
    if d.is_symlink():
        SOURCE_WARNINGS.append(f"{d} は symlink のため読みません (fail-closed)")
        return []
    if not d.is_dir():
        return []

    safe: list[Path] = []
    for f in d.glob("*.jsonl"):
        if f.is_symlink():
            SOURCE_WARNINGS.append(f"{f.name} は symlink のため読みません (fail-closed)")
            continue
        # 解決後も想定ディレクトリ直下に留まることを確認する
        if f.resolve().parent != d.resolve():
            SOURCE_WARNINGS.append(f"{f.name} が想定外の場所を指すため読みません (fail-closed)")
            continue
        if f.is_file():
            safe.append(f)
    return sorted(safe, key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_target(args) -> tuple[Path, list[Path]]:
    """対象 transcript を決める。候補はすべて同一リポジトリのルートに限る。"""
    primary, roots = resolve_root(args.project)

    found: list[Path] = []
    searched: list[Path] = []
    for root in roots:
        searched.append(project_dir(root))
        found.extend(find_transcripts(root))
    # 同じ実体を 2 度数えない (worktree とメインが同じルートに解決される場合)
    seen: set[Path] = set()
    unique = []
    for f in found:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    found = sorted(unique, key=lambda p: p.stat().st_mtime, reverse=True)

    if not found:
        detail = "\n".join(f"    {d}" for d in searched)
        warn = ("\n  読めなかったもの:\n" + "\n".join(f"    {w}" for w in SOURCE_WARNINGS)
                if SOURCE_WARNINGS else "")
        sys.exit(
            f"ERROR: このプロジェクトの transcript が見つかりません\n"
            f"  プロジェクト: {primary}\n"
            f"  探した場所:\n{detail}{warn}\n"
            f"  セッションの起動 cwd とずれている可能性があります。\n"
            f"  他プロジェクトは意図的に探しません (別案件=顧客の会話を読まないため)。"
        )
    if args.session:
        picked = [p for p in found if args.session in p.name]
        if not picked:
            sys.exit(
                f"ERROR: セッション '{args.session}' はこのプロジェクトにありません\n"
                f"  候補: {', '.join(p.stem for p in found)}"
            )
        return primary, picked[:1]
    if getattr(args, "all_sessions", False):
        return primary, found
    return primary, found[:1]


def print_warnings() -> None:
    """読めなかったものを必ず出す (黙って 0 件にしない)。"""
    for w in dict.fromkeys(SOURCE_WARNINGS):
        print(f"WARN: {w}", file=sys.stderr)


# --------------------------------------------------------------------------
# 読み出し
# --------------------------------------------------------------------------


def iter_records(path: Path):
    """jsonl を 1 レコードずつ返す。**dict 以外は捨てる**。

    壊れた行が「JSON としては妥当だがオブジェクトではない」ことがある
    (`[]` や `"partial"` 等)。そのまま流すと下流の `.get()` で全モードが
    落ちるため、ここで型を保証する。
    """
    with path.open(errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # 壊れた行は飛ばす (収集中に切れた場合など)
            if isinstance(rec, dict):
                yield rec


def message_text(content) -> str:
    """message.content から人間が書いたテキスト部分だけを連結する。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
    return "".join(parts)


def clean(text: str) -> str:
    text = SYSTEM_REMINDER_RE.sub("", text)
    text = CAVEAT_RE.sub("", text)
    return text.strip()


def is_human(text: str) -> bool:
    """人間が打った発話かどうか。

    スキル展開 (SKILL.md 本文がそのまま user ロールで入る) と、
    スラッシュコマンドの実行結果を除外する。これを外すと「人間はこう書いた」
    という教材の主張そのものが嘘になるので、判定は厳しめにする。
    """
    if not text:
        return False
    if text.startswith(SKILL_EXPANSION):
        return False
    return not any(marker in text for marker in COMMAND_MARKERS)


def collect_turns(paths: list[Path]) -> list[Turn]:
    turns: list[Turn] = []
    for path in paths:
        for rec in iter_records(path):
            if rec.get("type") != "user":
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            text = clean(message_text(msg.get("content")))
            if text == INTERRUPT:
                turns.append(Turn(len(turns) + 1, rec.get("timestamp", ""), text, "interrupt"))
                continue
            if not is_human(text):
                continue
            turns.append(Turn(len(turns) + 1, rec.get("timestamp", ""), text, "human"))
    return turns


def askuserquestion_ids(path: Path) -> set[str]:
    """AskUserQuestion として発行された tool_use の id を集める。"""
    ids: set[str] = set()
    for rec in iter_records(path):
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for item in content:
            if (isinstance(item, dict) and item.get("type") == "tool_use"
                    and item.get("name") == "AskUserQuestion" and item.get("id")):
                ids.add(item["id"])
    return ids


def collect_choices(paths: list[Path]) -> list[Choice]:
    """AskUserQuestion の「質問」と「実際に選ばれた回答」を対にする。

    **tool_use_id で辿る** (テキスト一致で拾わない)。理由: transcript を読む
    ツールの出力自体が transcript に記録されるため、`"質問"="回答"` という
    文字列を探すと **自分の過去の出力を再取り込みしてしまう** (実測: 8 対が
    16 対に化けた)。実行するたびに悪化する自己汚染なので、構造で辿る。
    """
    out: list[Choice] = []
    for path in paths:
        ids = askuserquestion_ids(path)
        if not ids:
            continue
        for rec in iter_records(path):
            if rec.get("type") != "user":
                continue
            msg = rec.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                if item.get("tool_use_id") not in ids:
                    continue
                body = item.get("content")
                text = body if isinstance(body, str) else message_text(body)
                for q, a in QA_PAIR_RE.findall(text):
                    out.append(Choice(unescape(q), unescape(a)))
    return out


def unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


# --------------------------------------------------------------------------
# 出力
# --------------------------------------------------------------------------


def cmd_list(args) -> int:
    root, _ = resolve_target(args)
    print(f"プロジェクト: {root}")
    print(f"transcript  : {project_dir(root)}")
    for p in find_transcripts(root):
        size = p.stat().st_size / 1024
        mtime = __import__("datetime").datetime.fromtimestamp(p.stat().st_mtime)
        print(f"  {mtime:%Y-%m-%d %H:%M}  {size:8.0f} KB  {p.stem}")
    return 0


def cmd_turns(args) -> int:
    _, paths = resolve_target(args)
    turns = collect_turns(paths)
    if args.json:
        print(json.dumps(
            [{"index": t.index, "timestamp": t.timestamp, "kind": t.kind, "text": t.text}
             for t in turns], ensure_ascii=False, indent=2))
        return 0
    print_warnings()
    for t in turns:
        marker = "▶" if t.kind == "human" else "⏸"
        stamp = t.timestamp[:16].replace("T", " ") if t.timestamp else ""
        print(f"{marker} [{t.index}] {stamp}")
        for line in t.text.splitlines():
            print(f"    {line}")
        print()
    print(f"--- 人間の発話 {sum(1 for t in turns if t.kind == 'human')} 件 "
          f"/ 中断 {sum(1 for t in turns if t.kind == 'interrupt')} 件")
    return 0


def cmd_choices(args) -> int:
    _, paths = resolve_target(args)
    choices = collect_choices(paths)
    if args.json:
        print(json.dumps([{"question": c.question, "answer": c.answer} for c in choices],
                         ensure_ascii=False, indent=2))
        return 0
    print_warnings()
    for i, c in enumerate(choices, 1):
        print(f"Q{i}. {c.question}")
        print(f"  → {c.answer}")
        print()
    print(f"--- 選択で答えた回数 {len(choices)} 件")
    return 0


def cmd_stats(args) -> int:
    _, paths = resolve_target(args)
    turns = collect_turns(paths)
    choices = collect_choices(paths)
    human = [t for t in turns if t.kind == "human"]
    chars = sum(len(t.text) for t in human)

    assistant = 0
    tools: dict[str, int] = {}
    for path in paths:
        for rec in iter_records(path):
            if rec.get("type") != "assistant":
                continue
            assistant += 1
            msg = rec.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        tools[item.get("name", "?")] = tools.get(item.get("name", "?"), 0) + 1

    print_warnings()
    print(f"人間の発話        : {len(human)} 件 ({chars} 文字)")
    print(f"中断 (steering)   : {sum(1 for t in turns if t.kind == 'interrupt')} 件")
    print(f"選択肢での回答    : {len(choices)} 件")
    print(f"Claude の応答     : {assistant} 件")
    print(f"ツール実行        : {sum(tools.values())} 回")
    for name, n in sorted(tools.items(), key=lambda x: -x[1])[:8]:
        print(f"  {name:<20} {n}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="transcript から人間の発話を取り出す")
    p.add_argument("--project", help="対象プロジェクトのルート (既定: git toplevel)")
    p.add_argument("--session", help="セッション ID の一部 (既定: 最新)")
    p.add_argument("--all-sessions", action="store_true",
                   dest="all_sessions", help="現プロジェクトの全セッションを対象")
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list", help="現プロジェクトの transcript 一覧").set_defaults(func=cmd_list)
    sub.add_parser("turns", help="人間が書いた発話を verbatim で出す").set_defaults(func=cmd_turns)
    sub.add_parser("choices", help="AskUserQuestion の質問と選ばれた回答").set_defaults(func=cmd_choices)
    sub.add_parser("stats", help="発話数・文字数・ツール実行回数").set_defaults(func=cmd_stats)

    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(sys.argv[1:] + ["turns"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
