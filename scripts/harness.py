#!/usr/bin/env python3
"""harness.py — .harness.yml の宣言を解決し、外部 LLM への送信を検知して伝える (根拠: ADR-0023)。

脅威モデル:
    Claude Code の通常利用での「うっかり送信」だけを扱う。**遮断はしない** — 送信の前に伝え、
    ログと /status の計器に残す。意図的な迂回や宣言の改ざんは対象外。

サブコマンド:
    resolve [PATH...]
        区分の解決結果を表示する (デバッグ用)
    egress-check [--vendor V]... [--url URL]... [--target PATH]... [--preflight] [--curl|--codex -- ARGS...]
        許可外の送信なら stderr に警告し、ログに残す。**常に exit 0** (処理を止めない)。
        判定対象は cwd の repo + --target + 環境変数 HARNESS_EGRESS_TARGETS (コロン区切り) のすべて。
        --preflight は送信前の事前チェック用で、ログに残さない (実際の送信側だけを数える)。
        --curl -- ARGS は curl の引数を解析し、本文を送る呼び出しだけを宛先ごとに判定する。
        --codex -- ARGS は codex の引数から -C/--cd/--add-dir を判定対象に加える
    status [--root DIR]
        /status 用の計器。問題があるときだけ 1 行ずつ出す (平時は無音)
    audit propose [--root DIR] [--gh]
        全 repo の区分案を ~/.config/agent-rules/harness/proposal.yml に書く (最終判断はユーザー)
    audit apply
        確認済みの案をローカル宣言として一括で書く

区分の解決 (ADR-0023 §4-1):
    1. repo の .harness.yml とローカル宣言のうち【厳しい方】を採る (上流の pull で区分が下がらない)
    2. どちらも無ければ「未宣言」。警告上は confidential と同じ
    3. 読めない (parse 失敗・PyYAML 不在・未知の値・git 外) は「判定不能」。黙って public に倒さない
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

LEVELS = {"public": 1, "internal": 2, "confidential": 3}
REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "config" / "egress.yml"


# --- 場所 ------------------------------------------------------------------
def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agent-rules" / "harness"


def log_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "agent-rules" / "egress.log"


def display(path: Path | str) -> str:
    s = str(path)
    home = str(Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


# --- YAML (PyYAML が無い環境でも検知器ごと落ちないよう遅延 import) -----------
class YamlUnavailable(Exception):
    pass


def load_yaml(path: Path):
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:
        raise YamlUnavailable from e
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def dump_yaml(data) -> str:
    import yaml  # noqa: PLC0415

    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def load_ledger(path: Path = LEDGER) -> dict:
    data = load_yaml(path)
    if not isinstance(data, dict) or not isinstance(data.get("vendors"), dict) or not isinstance(data.get("allow"), dict):
        raise ValueError("台帳の形式が不正です")
    return data


# --- git -------------------------------------------------------------------
def git(args: list[str], cwd: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def main_worktree(path: Path) -> Path | None:
    """worktree からでもメインワークツリーを返す (port-inventory.py と同じ復元方法)。"""
    d = path if path.is_dir() else path.parent
    while not d.exists() and d != d.parent:
        d = d.parent
    common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], d)
    if not common:
        return None
    common_p = Path(common)
    if common_p.name == ".git":
        return common_p.parent
    top = git(["rev-parse", "--show-toplevel"], d)  # submodule 等
    return Path(top) if top else None


_REMOTE_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?([^:/]+)(?::\d+)?[:/](.+?)(?:\.git)?/?$", re.I)


def normalize_remote(url: str) -> str | None:
    """git@host:org/repo.git / https://host/org/repo / ssh://git@host/org/repo.git → host/org/repo"""
    m = _REMOTE_RE.match(url.strip())
    if not m:
        return None
    return f"{m.group(1).lower()}/{m.group(2)}"


# --- 区分の解決 --------------------------------------------------------------
def read_decl(path: Path, kind: str) -> tuple[str | None, str | None]:
    """(区分, 問題) を返す。宣言が無ければ (None, None)。"""
    if not path.is_file():
        return None, None
    try:
        data = load_yaml(path)
    except YamlUnavailable:
        return None, "pyyaml-missing"
    except Exception:  # noqa: BLE001 — 形式の壊れた宣言は「判定不能」として伝える
        return None, "parse-error"
    if not isinstance(data, dict) or data.get("harness") != 1:
        # repo 側の同名ファイルは無関係なもの (CI/CD 製品 Harness 等) かもしれない → 未宣言扱い
        return (None, None) if kind == "repo" else (None, "schema-unknown")
    level = data.get("sensitivity")
    if not isinstance(level, str) or level not in LEVELS:
        return None, "unknown-value"
    return level, None


def resolve(path: str | Path) -> dict:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        pass
    res = {"path": str(p), "root": None, "repo": None, "level": None,
           "status": "unknown", "reason": None, "sources": []}
    root = main_worktree(p)
    if root is None:
        res["reason"] = "not-a-git-repo"
        return res
    res["root"] = str(root)
    remote = git(["config", "--get", "remote.origin.url"], root)
    rid = normalize_remote(remote) if remote else None
    res["repo"] = rid

    levels, problems = [], []
    candidates = [(root / ".harness.yml", "repo", "repo の .harness.yml")]
    if rid:
        candidates.append((config_home() / f"{rid}.yml", "local", "ローカル宣言"))
    for decl, kind, label in candidates:
        level, problem = read_decl(decl, kind)
        if problem:
            problems.append(problem)
        elif level:
            levels.append(level)
            res["sources"].append(f"{label}: {level}")

    if levels:
        res["level"] = max(levels, key=LEVELS.__getitem__)
    if problems:
        res["status"], res["reason"] = "unknown", problems[0]
    elif levels:
        res["status"] = "declared"
    else:
        res["status"] = "undeclared"
    return res


def allow_key(res: dict) -> str:
    # 判定不能でも、読めた宣言が confidential ならそれで判定する (より厳しい側)
    if res["status"] == "declared" or (res["status"] == "unknown" and res["level"] == "confidential"):
        return res["level"]
    return "undeclared"


# --- egress-check ----------------------------------------------------------
REASONS = {
    "not-a-git-repo": "git リポジトリの外",
    "pyyaml-missing": "PyYAML がありません",
    "parse-error": "宣言ファイルを読めません",
    "schema-unknown": "ローカル宣言の形式が不明です",
    "unknown-value": "sensitivity の値が不明です",
    "ledger-unreadable": "送信先台帳 config/egress.yml を読めません",
}


def vendor_for_url(ledger: dict, url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for key, v in ledger["vendors"].items():
        if host in [h.lower() for h in v.get("hosts", [])]:
            return key
    return None


def write_log(entry: dict) -> None:
    try:
        lp = log_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        with open(lp, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # ログが書けなくても通知 (stderr) は済んでいる


def emit(lines: list[str]) -> None:
    print("\n".join(lines), file=sys.stderr)


def collect_targets(args_targets: list[str]) -> list[str]:
    """cwd は常に含める — 公開ファイルを参照しつつ機密案件の文脈を送る場合も拾う (設計 §6-2)。"""
    targets = [os.getcwd(), *[t for t in args_targets if t]]
    env = os.environ.get("HARNESS_EGRESS_TARGETS", "")
    targets += [t for t in env.split(":") if t]
    return list(dict.fromkeys(targets))


# curl の引数: 本文を送るオプションと、値を取るオプション (値を宛先と誤認しないため)
CURL_BODY = {"-d", "--data", "--data-ascii", "--data-binary", "--data-raw", "--data-urlencode",
             "-F", "--form", "--form-string", "--json", "-T", "--upload-file"}
CURL_VALUE = CURL_BODY | {
    "-H", "--header", "-o", "--output", "-m", "--max-time", "-X", "--request", "-u", "--user",
    "-A", "--user-agent", "-e", "--referer", "-K", "--config", "-b", "--cookie", "-c", "--cookie-jar",
    "-w", "--write-out", "--connect-timeout", "--retry", "-x", "--proxy", "--resolve", "--cacert",
    "--cert", "--key", "-E", "-r", "--range", "-z", "--time-cond", "-D", "--dump-header", "-Y", "-y"}
CURL_SHORT_BODY, CURL_SHORT_VALUE = set("dFT"), set("dFTHomXuAeKbcwxErzDYy")


def parse_curl(argv: list[str]) -> tuple[bool, list[str]]:
    """(本文を送るか, 宛先 URL のリスト) を返す。"""
    body, urls, i = False, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--url":
            urls += argv[i + 1:i + 2]
            i += 2
            continue
        if a.startswith("--url="):
            urls.append(a[len("--url="):])
        elif a.startswith("--") and "=" in a:
            body |= a.split("=", 1)[0] in CURL_BODY
        elif a in CURL_VALUE:
            body |= a in CURL_BODY
            i += 2
            continue
        elif re.fullmatch(r"-[A-Za-z]+", a):
            # 結合した短いオプション (-sf / -sfm 20)。最後の文字だけが値を取りうる
            body |= a[-1] in CURL_SHORT_BODY
            if a[-1] in CURL_SHORT_VALUE:
                i += 2
                continue
        elif re.match(r"-[dFT].", a):
            body = True  # -d@- / -d'{}' のような値の結合表記
        elif re.match(r"https?://", a, re.I):
            urls.append(a)
        i += 1
    return body, urls


def parse_codex(argv: list[str]) -> list[str]:
    """codex の -C/--cd/--add-dir (作業ディレクトリ・追加ディレクトリ) を判定対象として返す。"""
    dirs, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("-C", "--cd", "--add-dir"):
            dirs += argv[i + 1:i + 2]
            i += 2
            continue
        for opt in ("--cd=", "--add-dir="):
            if a.startswith(opt):
                dirs.append(a[len(opt):])
        i += 1
    return dirs


def cmd_egress_check(args) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        ledger = load_ledger()
    except Exception:  # noqa: BLE001
        emit(["⚠ 外部送信の確認 (ADR-0023): 送信先台帳 config/egress.yml を読めず、区分を判定できませんでした。"])
        write_log({"ts": now, "kind": "unknown", "reason": "ledger-unreadable"})
        return 0

    vendors = list(dict.fromkeys(args.vendor or []))
    urls = list(args.url or [])
    targets = list(args.target or [])
    if args.curl is not None:
        body, curl_urls = parse_curl(args.curl)
        if not body:
            return 0  # 本文の無い GET (モデル存在確認・残高確認) は内容を送らない (Fable A-9)
        urls += curl_urls
    if args.codex is not None:
        targets += parse_codex(args.codex)
    host = None
    for url in urls:
        if url in (ledger.get("metadata_urls") or []):
            continue
        v = vendor_for_url(ledger, url)
        if v is None:
            continue  # 台帳に無い宛先は対象外 (通常利用の送信はすべて台帳にある — コーパス試験で担保)
        vendors.append(v)
        host = urlparse(url).hostname
    vendors = list(dict.fromkeys(vendors))
    if not vendors:
        return 0
    unknown_vendors = [v for v in vendors if v not in ledger["vendors"]]
    vendors = [v for v in vendors if v in ledger["vendors"]]
    if unknown_vendors:
        emit([f"⚠ 外部送信の確認 (ADR-0023): 台帳に無いベンダー {', '.join(unknown_vendors)} が指定されました。config/egress.yml を確認してください。"])

    results = [resolve(t) for t in collect_targets(targets)]
    allow = ledger["allow"]
    for vendor in vendors:
        flagged = [r for r in results if vendor not in (allow.get(allow_key(r)) or [])]
        if not flagged:
            continue
        vinfo = ledger["vendors"][vendor]
        dest = vinfo.get("name", vendor) + (f" ({host})" if host else "")
        lines = [f"⚠ 外部送信の確認 (ADR-0023): この送信は {dest} に届きます。"]
        for r in flagged:
            where = display(r["root"] or r["path"])
            if r["status"] == "declared":
                lines.append(f"   対象 {where} の区分は {r['level']} です ({' / '.join(r['sources'])})。")
            elif r["status"] == "undeclared":
                lines.append(f"   対象 {where} は区分が未宣言です (/harness-audit で区分を付けられます)。")
            else:
                lines.append(f"   対象 {where} の区分を判定できませんでした (理由: {r['reason']} — {REASONS.get(r['reason'], '')})。")
        lines.append("   止めるには中断してください。意図どおりなら、このまま続行されます。")
        emit(lines)
        if args.preflight:
            continue  # 事前チェックは記録しない (実際の送信側で 1 回だけ数える)
        write_log({
            "ts": now,
            "kind": "unknown" if any(r["status"] == "unknown" for r in flagged) else "warn",
            "vendor": vendor, "host": host,
            "targets": [{k: r[k] for k in ("root", "path", "repo", "level", "status", "reason")} for r in flagged],
        })
    return 0


def cmd_resolve(args) -> int:
    for t in args.paths or [os.getcwd()]:
        print(json.dumps(resolve(t), ensure_ascii=False))
    return 0


# --- status (計器) ----------------------------------------------------------
def find_repos(root: Path) -> list[Path]:
    """<root>/<host>/<org>/<repo> の git リポジトリ (worktree 置き場 *-worktrees は除く)。"""
    repos = []
    for d in sorted(root.glob("*/*/*")):
        if d.is_dir() and (d / ".git").exists() and not d.parent.name.endswith("-worktrees"):
            repos.append(d)
    return repos


def cmd_status(args) -> int:
    lines = []
    try:
        load_ledger()
    except Exception:  # noqa: BLE001
        lines.append("⚠ 送信先台帳 config/egress.yml を読めません — 外部送信の検知が働いていません (ADR-0023)")

    warn = unknown = 0
    lp = log_path()
    if lp.is_file():
        since = datetime.now(timezone.utc) - timedelta(days=7)
        for line in lp.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
                if datetime.fromisoformat(e["ts"]) < since:
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            if e.get("kind") == "warn":
                warn += 1
            elif e.get("kind") == "unknown":
                unknown += 1
    if warn:
        lines.append(f"外部送信の警告: 直近 7 日で {warn} 件 (ログ: {display(lp)})")
    if unknown:
        lines.append(f"外部送信の区分を判定できなかった送信: 直近 7 日で {unknown} 件 (ログ: {display(lp)})")

    root = Path(args.root).expanduser()
    if root.is_dir():
        undeclared = [r for r in find_repos(root) if resolve(r)["status"] == "undeclared"]
        if undeclared:
            lines.append(f"区分が未宣言の repo: {len(undeclared)} 件 (送信のたびに警告が出ます) → /harness-audit で区分を付けられます")
    if lines:
        print("\n".join(lines))
    return 0


# --- audit (初回の区分付け) -------------------------------------------------
def proposal_path() -> Path:
    return config_home() / "proposal.yml"


def gh_visibility(orgs: set[str]) -> tuple[dict[str, str], list[str]]:
    vis, failed = {}, []
    for host_org in sorted(orgs):
        host, org = host_org.split("/", 1)
        if host != "github.com":
            continue
        try:
            r = subprocess.run(
                ["gh", "repo", "list", org, "--limit", "1000", "--json", "name,visibility"],
                capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
            )
            if r.returncode != 0:
                failed.append(org)
                continue
            for item in json.loads(r.stdout):
                vis[f"github.com/{org}/{item['name']}".lower()] = item["visibility"]
        except (OSError, subprocess.SubprocessError, ValueError):
            failed.append(org)
    return vis, failed


def cmd_audit_propose(args) -> int:
    root = Path(args.root).expanduser()
    repos = find_repos(root)
    resolved = [(r, resolve(r)) for r in repos]
    vis, failed = ({}, [])
    if args.gh:
        orgs = {"/".join(res["repo"].split("/")[:2]) for _, res in resolved if res["repo"]}
        vis, failed = gh_visibility(orgs)

    entries = []
    for path, res in resolved:
        rid = res["repo"]
        if res["status"] == "declared":
            proposed, basis = res["level"], "既存の宣言 (" + " / ".join(res["sources"]) + ")"
        elif rid and vis.get(rid.lower()) == "PUBLIC":
            proposed, basis = "public", "GitHub で公開されている"
        else:
            proposed, basis = "confidential", "非公開 (既定)。社内だけのものは internal に下げてください"
        entries.append({"repo": rid, "path": display(path), "sensitivity": proposed, "basis": basis})

    header = (
        "# /harness-audit の区分案 (ADR-0023)。案件名を含むためローカル専用 — コミットしない。\n"
        "# 各行の sensitivity (public | internal | confidential) を確認・修正してから\n"
        "#   python3 ~/repos/github.com/elm-inc/agent-rules/scripts/harness.py audit apply\n"
        "# で、全 repo のローカル宣言を一括で書く。repo が空 (origin 無し) の行は書けないのでスキップされる。\n"
    )
    pp = proposal_path()
    pp.parent.mkdir(parents=True, exist_ok=True)
    pp.write_text(header + dump_yaml({"entries": entries}), encoding="utf-8")

    counts = {k: sum(1 for e in entries if e["sensitivity"] == k) for k in LEVELS}
    print(f"区分案を書きました: {display(pp)}")
    print(f"  {len(entries)} repo — public {counts['public']} / internal {counts['internal']} / confidential {counts['confidential']}")
    if failed:
        print(f"  ※ GitHub の公開状態を取得できなかった org: {', '.join(failed)} (非公開として扱いました)")
    return 0


def cmd_audit_apply(args) -> int:
    pp = proposal_path()
    if not pp.is_file():
        print(f"区分案がありません: {display(pp)} — 先に audit propose を実行してください", file=sys.stderr)
        return 1
    data = load_yaml(pp) or {}
    written = skipped = 0
    for e in data.get("entries") or []:
        rid, level = e.get("repo"), e.get("sensitivity")
        if not rid or level not in LEVELS:
            skipped += 1
            continue
        decl = config_home() / f"{rid}.yml"
        current = {}
        if decl.is_file():
            try:
                current = load_yaml(decl) or {}
            except Exception:  # noqa: BLE001
                current = {}
        current = current if isinstance(current, dict) else {}
        current["harness"] = 1
        current["sensitivity"] = level  # stack: 等の他のキーは保持する
        decl.parent.mkdir(parents=True, exist_ok=True)
        decl.write_text(dump_yaml(current), encoding="utf-8")
        written += 1
    print(f"ローカル宣言を書きました: {written} 件 (スキップ {skipped} 件) — {display(config_home())}")
    return 0


# --- CLI -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="harness.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("resolve")
    p.add_argument("paths", nargs="*")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("egress-check")
    p.add_argument("--vendor", action="append")
    p.add_argument("--url", action="append")
    p.add_argument("--target", action="append")
    p.add_argument("--preflight", action="store_true", help="送信前の事前チェック (ログに残さない)")
    p.add_argument("--curl", action="store_true", help="-- 以降を curl の引数として解析する")
    p.add_argument("--codex", action="store_true", help="-- 以降を codex の引数として解析する")
    p.set_defaults(func=cmd_egress_check)

    default_root = str(Path.home() / "repos")
    p = sub.add_parser("status")
    p.add_argument("--root", default=default_root)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("audit")
    asub = p.add_subparsers(dest="audit_cmd", required=True)
    pp = asub.add_parser("propose")
    pp.add_argument("--root", default=default_root)
    pp.add_argument("--gh", action="store_true", help="gh で GitHub の公開状態を取得して案に使う")
    pp.set_defaults(func=cmd_audit_propose)
    pa = asub.add_parser("apply")
    pa.set_defaults(func=cmd_audit_apply)

    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough = None
    if "--" in argv:  # egress-check --curl/--codex -- <そのコマンドの引数>
        cut = argv.index("--")
        argv, passthrough = argv[:cut], argv[cut + 1:]
    args = ap.parse_args(argv)
    if args.cmd == "egress-check":
        args.curl = passthrough if args.curl else None
        args.codex = passthrough if args.codex else None
        # 検知器の不具合で送信側の処理を止めない (Sensor であって Gate ではない)。ただし黙らず、計器にも残す
        try:
            return args.func(args)
        except Exception as e:  # noqa: BLE001
            emit([f"⚠ 外部送信の確認 (ADR-0023): 検知器の内部エラーで区分を判定できませんでした ({type(e).__name__})。"])
            if not args.preflight:
                write_log({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "kind": "unknown", "reason": f"internal-error:{type(e).__name__}"})
            return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
