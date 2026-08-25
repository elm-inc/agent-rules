#!/usr/bin/env python3
"""transcript-extract.py の回帰テスト (依存なし・pytest 不要)。

固定しているのは 2 種類:

1. **fail-closed の保証** — 別案件の transcript を読まないこと。破れても
   エラーにならず、正しいパスを表示したまま他人の会話を読むので気づけない
2. **人間の発話判定** — 教材が「人間はこう書いた」と主張する根拠。誤判定すると
   スキル展開やコマンド出力を人間の発言として載せてしまう

実行: python3 scripts/test-transcript-extract.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("transcript-extract.py")
spec = importlib.util.spec_from_file_location("transcript_extract", MODULE_PATH)
assert spec and spec.loader
te = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = te  # dataclass の解決に必要
spec.loader.exec_module(te)

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")


def write_jsonl(path: Path, records: list) -> None:
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def user_text(text: str) -> dict:
    return {"type": "user", "timestamp": "2026-08-25T00:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


# --------------------------------------------------------------------------
# 人間の発話判定
# --------------------------------------------------------------------------

check("素の発話は人間", te.is_human("ポートを一覧したい"), True)
check("空は人間ではない", te.is_human(""), False)
check("スキル展開は除外",
      te.is_human("Base directory for this skill: /home/x/.claude/skills/ports\n# ..."), False)
check("スラッシュコマンドの実行結果は除外",
      te.is_human("<command-name>/status</command-name>"), False)
check("コマンド出力は除外",
      te.is_human("<local-command-stdout>ok</local-command-stdout>"), False)

check("system-reminder は落とす",
      te.clean("本文<system-reminder>内部メモ</system-reminder>"), "本文")
check("複数行の system-reminder も落とす",
      te.clean("前<system-reminder>a\nb\nc</system-reminder>後"), "前後")
check("caveat も落とす",
      te.clean("<local-command-caveat>注意</local-command-caveat>本文"), "本文")

# --------------------------------------------------------------------------
# AskUserQuestion の対応付け
# --------------------------------------------------------------------------

qa = 'Your questions have been answered: "スコープは?"="検知のみ", "範囲は?"="全体".'
check("質問と回答の対を取れる",
      te.QA_PAIR_RE.findall(qa), [("スコープは?", "検知のみ"), ("範囲は?", "全体")])
check("エスケープを戻す", te.unescape('a\\"b'), 'a"b')

with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "s.jsonl"
    write_jsonl(f, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_1", "name": "AskUserQuestion", "input": {}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1",
             "content": 'Your questions have been answered: "本物?"="はい".'}]}},
        # 別ツールの出力に同じ形の文字列が含まれるケース (= 自分の過去出力の再取り込み)
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_2",
             "content": 'Your questions have been answered: "偽物?"="ひろう厳禁".'}]}},
    ])
    got = te.collect_choices([f])
    check("AskUserQuestion 由来だけを拾う", [(c.question, c.answer) for c in got],
          [("本物?", "はい")])

# --------------------------------------------------------------------------
# 壊れた JSONL でクラッシュしない
# --------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "broken.jsonl"
    f.write_text(
        "[]\n"                                   # JSON だがオブジェクトでない
        '"partial"\n'                            # 同上
        "123\n"                                  # 同上
        "{not json}\n"                           # そもそも壊れている
        "\n"                                     # 空行
        + json.dumps(user_text("生き残る発話"), ensure_ascii=False) + "\n"
        + json.dumps({"type": "user", "message": "文字列の message"}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "user", "message": {"content": {"dict": "想定外"}}},
                     ensure_ascii=False) + "\n"
    )
    check("非 dict レコードを捨てる", all(isinstance(r, dict) for r in te.iter_records(f)), True)
    turns = te.collect_turns([f])
    check("壊れた行を飛ばして人間の発話だけ拾う",
          [t.text for t in turns], ["生き残る発話"])
    check("壊れた入力でも choices が落ちない", te.collect_choices([f]), [])

# --------------------------------------------------------------------------
# fail-closed: symlink を辿らない
# --------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "repo"
    root.mkdir()
    other = Path(tmp) / "other-customer"
    other.mkdir()
    write_jsonl(other / "leak.jsonl", [user_text("別案件の会話")])

    projects = Path(tmp) / "projects"
    projects.mkdir()
    te.PROJECTS_ROOT = projects
    te.SOURCE_WARNINGS.clear()

    # ディレクトリごと symlink
    (projects / te.encode_project(root)).symlink_to(other)
    check("symlink のディレクトリは読まない", te.find_transcripts(root), [])
    check("理由を記録する", any("symlink" in w for w in te.SOURCE_WARNINGS), True)

    # ディレクトリは実体、中の jsonl が symlink
    (projects / te.encode_project(root)).unlink()
    real_dir = projects / te.encode_project(root)
    real_dir.mkdir()
    (real_dir / "linked.jsonl").symlink_to(other / "leak.jsonl")
    write_jsonl(real_dir / "own.jsonl", [user_text("自分の会話")])
    te.SOURCE_WARNINGS.clear()
    found = te.find_transcripts(root)
    check("symlink の jsonl を除外する", [p.name for p in found], ["own.jsonl"])
    check("除外の理由を記録する", any("symlink" in w for w in te.SOURCE_WARNINGS), True)
    check("残ったものは読める",
          [t.text for t in te.collect_turns(found)], ["自分の会話"])

# --------------------------------------------------------------------------
# 出力の形
# --------------------------------------------------------------------------

check("プロジェクト名のエンコード規則",
      te.encode_project(Path("/home/u/repos/github.com/org/repo")),
      "-home-u-repos-github-com-org-repo")

with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "s.jsonl"
    write_jsonl(f, [
        user_text("ひとつめ"),
        {"type": "user", "message": {"role": "user",
                                     "content": [{"type": "text", "text": te.INTERRUPT}]}},
        user_text("ふたつめ"),
    ])
    turns = te.collect_turns([f])
    check("中断を human と混ぜない", [t.kind for t in turns],
          ["human", "interrupt", "human"])
    check("通し番号が振られる", [t.index for t in turns], [1, 2, 3])

# --------------------------------------------------------------------------

if failures:
    print(f"FAIL: {len(failures)} 件")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ok: transcript-extract の抽出ロジック 全件通過")
