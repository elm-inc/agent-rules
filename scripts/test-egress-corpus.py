#!/usr/bin/env python3
"""test-egress-corpus.py — 外部 LLM への送信がすべて送信ヘルパを通っているかを検査する (ADR-0023 AC-1)。

外部送信の検知は送信ヘルパ (config/egress.yml の helpers) に置いてある。ヘルパを経由しない送信が
スキルやスクリプトに新しく書かれると、その経路だけ黙って検知から漏れる。ここで機械的に落とす。

検査対象:
    - skills/**/*.md と agents/**/*.md の【fenced code block】(散文での言及は実行されないので見ない)
    - skills/**/scripts/**・scripts/** の全行
    - 行末の `\\` で続く行は 1 行に結合してから見る (継続行の URL を見落とさない — Fable A-1)

違反とみなすもの (判定の単位は md の fenced block 1 つ、またはスクリプト 1 ファイル):
    - 単位の中に生の HTTP クライアント呼び出し (curl/wget/urlopen/requests/httpx/fetch) があり、かつ
      台帳の外部ベンダー (全区分で許可されているローカル LLM を除く) のホストが、ヘルパ (curl_auth_*) の
      論理行の【外】に現れる。行単位で見ると `URL=...; curl "$URL"` や複数行の `httpx.post(` を見逃すため
      (codex-review 指摘)
    - `codex ... exec` / `codex ... review` の直接呼び出し (途中のオプション `--profile x` 等も含む)。
      codex-run.sh / codex-astra.sh を使う
    - コメント行 (`#` 始まり) は実行されないので見ない。例外は行内の `egress:allow` マーカーだけ

    python3 scripts/test-egress-corpus.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
LEDGER = yaml.safe_load((REPO / "config" / "egress.yml").read_text(encoding="utf-8"))
SELF = {"scripts/test-egress-corpus.py", "scripts/test-harness.py"}

ALWAYS_ALLOWED = set.intersection(*(set(v) for v in LEDGER["allow"].values()))
HOSTS = sorted({h for k, v in LEDGER["vendors"].items() if k not in ALWAYS_ALLOWED for h in v["hosts"]})
HOST_RE = re.compile("|".join(re.escape(h) for h in HOSTS))
CLIENT_RE = re.compile(r"\bcurl\b|\bwget\b|urlopen|requests\.\w+\(|httpx|\bfetch\(")
HELPER_RE = re.compile(r"\bcurl_auth_(bearer|header)\b")
# codex の後ろが語・ドット・ハイフンで続くもの (codex-run.sh / codex-astra.sh) は別コマンドなので除く
CODEX_RE = re.compile(r"(^|[\s;&|(`$])codex(?![\w.-])[^\n;&|]*?\s(exec|review)\b")
COMMENT_RE = re.compile(r"^\s*#")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def logical_lines(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    out, buf, start = [], "", None
    for no, line in lines:
        if start is None:
            start = no
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        out.append((start, buf + line))
        buf, start = "", None
    if buf:
        out.append((start, buf))
    return out


def units(path: Path, text: str) -> list[list[tuple[int, str]]]:
    """判定の単位: md は fenced block ごと、それ以外はファイル全体。"""
    lines = list(enumerate(text.splitlines(), 1))
    if path.suffix != ".md":
        return [lines]
    blocks, cur, inside = [], [], False
    for no, line in lines:
        if FENCE_RE.match(line):
            if inside:
                blocks.append(cur)
                cur = []
            inside = not inside
            continue
        if inside:
            cur.append((no, line))
    return blocks


def violations(rel: str, text: str) -> list[str]:
    found = []
    for unit in units(Path(rel), text):
        lls = [(no, l) for no, l in logical_lines(unit) if not COMMENT_RE.match(l) and "egress:allow" not in l]
        raw_client = any(CLIENT_RE.search(l) and not HELPER_RE.search(l) for _, l in lls)
        for no, line in lls:
            if raw_client and HOST_RE.search(line) and not HELPER_RE.search(line):
                found.append(f"{rel}:{no}: 送信ヘルパを経由しない外部送信: {line.strip()[:120]}")
            if CODEX_RE.search(line):
                found.append(f"{rel}:{no}: codex を直接呼んでいる (scripts/codex-run.sh を使う): {line.strip()[:120]}")
    return found


def corpus() -> list[Path]:
    files = set(REPO.glob("skills/**/*.md")) | set(REPO.glob("agents/**/*.md"))
    files |= {p for p in REPO.glob("skills/**/scripts/**/*") if p.is_file()}
    files |= {p for p in REPO.glob("scripts/**/*") if p.is_file() and "__pycache__" not in p.parts}
    helpers = set(LEDGER["helpers"])
    return sorted(p for p in files if str(p.relative_to(REPO)) not in helpers | SELF)


class CorpusTest(unittest.TestCase):
    def test_all_egress_goes_through_helpers(self):
        found = []
        for p in corpus():
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found += violations(str(p.relative_to(REPO)), text)
        self.assertEqual(found, [], "\n" + "\n".join(found))

    # 変異注入: 検査器自体が穴を見つけられることを確認する (Fable F-2)
    def test_detects_raw_curl_in_script(self):
        self.assertTrue(violations("scripts/x.sh", 'curl -sf https://api.deepseek.com/v1/chat/completions -d "$P"\n'))

    def test_detects_raw_curl_in_skill_script(self):
        self.assertTrue(violations("skills/x/scripts/y.sh", "curl -s \\\n  https://generativelanguage.googleapis.com/v1beta/models/m:generateContent -d @-\n"))

    def test_detects_python_client(self):
        self.assertTrue(violations("scripts/x.py", 'httpx.post("https://api.openai.com/v1/responses", json=p)\n'))

    def test_detects_raw_curl_in_md_fence(self):
        self.assertTrue(violations("skills/x/SKILL.md", "```bash\ncurl https://api.deepseek.com/v1/chat/completions -d x\n```\n"))

    def test_detects_direct_codex(self):
        self.assertTrue(violations("skills/x/SKILL.md", '```bash\ncodex exec --sandbox read-only "x"\n```\n'))
        self.assertTrue(violations("skills/x/SKILL.md", "```bash\ncodex review --uncommitted\n```\n"))

    def test_detects_codex_with_options(self):  # codex-review: AGENTS.md の通常利用形
        self.assertTrue(violations("skills/x/SKILL.md", '```bash\ncodex --profile agent-rules exec "x"\n```\n'))

    def test_detects_url_via_variable(self):  # codex-review: 変数経由の URL
        self.assertTrue(violations("scripts/x.sh", 'URL=https://api.deepseek.com/v1/chat/completions\ncurl -sf "$URL" -d "$P"\n'))

    def test_detects_multiline_python_call(self):  # codex-review: 括弧内で改行した呼び出し
        self.assertTrue(violations("scripts/x.py", 'r = httpx.post(\n    "https://api.openai.com/v1/responses",\n    json=p,\n)\n'))

    def test_allows_helper_with_continuation(self):
        self.assertFalse(violations("skills/x/SKILL.md", '```bash\nR=$(curl_auth_bearer "$K" -sf \\\n  https://api.deepseek.com/v1/chat/completions \\\n  -d "$P")\n```\n'))

    def test_allows_wrapper_and_prose(self):
        self.assertFalse(violations("skills/x/SKILL.md", '```bash\n~/repos/github.com/elm-inc/agent-rules/scripts/codex-run.sh exec "x"\n```\n'))
        self.assertFalse(violations("skills/x/SKILL.md", "エンドポイント: `curl` で `https://api.deepseek.com` を呼ぶ\n"), "散文は見ない")
        self.assertFalse(violations("scripts/x.sh", 'curl -sf http://localhost:8000/v1/chat/completions -d "$P"\n'), "ローカル LLM は対象外")
        self.assertFalse(violations("scripts/x.sh", '# https://api.deepseek.com を curl で叩く例\ncurl -sf http://localhost:8000/x -d "$P"\n'), "コメントは見ない")
        self.assertFalse(violations("skills/x/SKILL.md", '```bash\n"$CODEX" review --uncommitted\n./scripts/codex-astra.sh review --base main\n```\n'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
