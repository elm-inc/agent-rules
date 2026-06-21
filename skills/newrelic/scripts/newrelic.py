#!/usr/bin/env python3
"""newrelic — マルチテナント安全な New Relic (NerdGraph) クライアント。

受託では案件ごとに別顧客の New Relic テナントを触る。間違ったテナントへのクエリは
顧客データの混線になる。このスクリプトは「いまどの顧客アカウントを見ているか」を
常に明示・検証可能にし、暗黙の既定に倒さない (fail-closed) ことを最優先する。

設計の根拠: docs/adr/0008-newrelic-connection-hybrid.md (+ redteam 追記 §A-G)
詳細設計:   docs/design/newrelic-skill.md

Subcommands:
  whoami              いま解決される profile と「鍵が実際に見える account/region」を表示
  doctor              3者一致検証 (.mcp.json region == profile == 鍵が見える account)
  nrql "<NRQL>"       NerdGraph で NRQL 実行 (account は profile から)
  entities [--query]  エンティティ検索 (entitySearch)
  dashboards list|get ダッシュボード一覧 / 取得
  alerts   list|policies  アラート参照 (書込系は profile 再表示して確認)
  profile  list|show|path profile 一覧(名前のみ) / 解決結果 / パス
  init [dir] --profile N  per-project 雛形展開 (.newrelic-profile + .mcp.json 生成 + .gitignore)

profile 解決順 (fail-closed): --profile > repo の .newrelic-profile > エラー
鍵の出所:   ~/.newrelic/<profile>.env (perms 600, key+account+region)
設定の解決順: 引数 > 環境変数 (NEWRELIC_*) > ~/.config/newrelic.toml > 既定値
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27", "tomli; python_version<'3.11'"]
# ///

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_PATH = Path.home() / ".config" / "newrelic.toml"
PROFILE_DIR = Path.home() / ".newrelic"
AUDIT_LOG = PROFILE_DIR / "audit.log"
STATE_DIR = Path(os.environ.get("NEWRELIC_CACHE_DIR", str(Path.home() / ".cache" / "newrelic")))

# リージョンごとのエンドポイント (US 既定 / EU 切替)。profile.region で選ぶ。
REGIONS = {
    "us": {"graphql": "https://api.newrelic.com/graphql", "mcp": "https://mcp.newrelic.com/mcp/"},
    "eu": {"graphql": "https://api.eu.newrelic.com/graphql", "mcp": "https://mcp.eu.newrelic.com/mcp/"},
}
DEFAULT_REGION = "us"
REQUIRED_KEYS = ("NEW_RELIC_API_KEY", "NEW_RELIC_ACCOUNT_ID", "NEW_RELIC_REGION")

DEFAULTS = {
    "max_concurrency": 8,   # NerdGraph 同時25/user の下に自前の床
    "min_interval_ms": 0,   # 全プロセス共有の最小送信間隔 (既定 0 = 床なし)
    "max_retries": 4,       # 429/5xx のリトライ上限
    "timeout_s": 60,
}


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------- config ----------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    return {}


def cfg(args: argparse.Namespace, key: str):
    val = getattr(args, key, None)
    if val is not None:
        return val
    env = os.environ.get(f"NEWRELIC_{key.upper()}")
    if env is not None:
        return type(DEFAULTS[key])(env) if key in DEFAULTS else env
    c = load_config()
    if key in c:
        return c[key]
    return DEFAULTS.get(key)


# ---------- profile 解決 (fail-closed; ADR §C) ----------

def find_profile_file() -> Path | None:
    """cwd から repo ルート (.git を含む dir) まで上って .newrelic-profile を探す。

    親 repo の設定をうっかり継承して別顧客を指す事故 (redteam) を避けるため、
    探索は repo 境界で打ち切る。見つからなければ None (→ 呼び出し側で fail-closed)。
    """
    cur = Path.cwd().resolve()
    home = Path.home().resolve()
    while True:
        p = cur / ".newrelic-profile"
        if p.exists():
            return p
        if (cur / ".git").exists():
            return None  # repo ルート到達。ここより上は見に行かない
        if cur == cur.parent or cur == home:
            return None
        cur = cur.parent


def resolve_profile_name(args: argparse.Namespace) -> str:
    if getattr(args, "profile", None):
        return args.profile.strip()
    pf = find_profile_file()
    if pf is None:
        die("profile を解決できません。--profile <名> を指定するか、repo 直下に "
            ".newrelic-profile を置いてください (暗黙の既定には倒しません)")
    name = pf.read_text().strip()
    if not name or "\n" in name:
        die(f"{pf} が空または不正です (profile 名を1行で記述してください)")
    return name


def load_profile(name: str) -> dict:
    """~/.newrelic/<name>.env を読み、検証して dict を返す。検証失敗は即エラー。"""
    path = PROFILE_DIR / f"{name}.env"
    if not path.exists():
        avail = sorted(p.stem for p in PROFILE_DIR.glob("*.env")) if PROFILE_DIR.exists() else []
        die(f"profile '{name}' がありません: {path}\n  利用可能: {', '.join(avail) or '(なし)'}")
    mode = path.stat().st_mode & 0o077
    if mode != 0:
        die(f"{path} のパーミッションが緩すぎます (group/other に読取権)。chmod 600 してください")
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing:
        die(f"profile '{name}' に必須キー不足: {', '.join(missing)}")
    region = env["NEW_RELIC_REGION"].lower()
    if region not in REGIONS:
        die(f"profile '{name}' の region 不正: {region} (us|eu のみ)")
    if not env["NEW_RELIC_ACCOUNT_ID"].isdigit():
        die(f"profile '{name}' の NEW_RELIC_ACCOUNT_ID は数値である必要があります")
    key = env["NEW_RELIC_API_KEY"]
    # EU 鍵 prefix の sanity check (取り違え検出)。EU 鍵は 'EU' で始まる。
    is_eu_key = key.upper().startswith("EU")
    if region == "eu" and not is_eu_key:
        die(f"profile '{name}': region=eu だが鍵が EU prefix でありません (取り違えの疑い)")
    if region == "us" and is_eu_key:
        die(f"profile '{name}': region=us だが鍵が EU prefix です (取り違えの疑い)")
    return {
        "name": name,
        "api_key": key,
        "account_id": int(env["NEW_RELIC_ACCOUNT_ID"]),
        "region": region,
        "mcp_allowed": env.get("NEW_RELIC_MCP_ALLOWED", "true").lower() != "false",
    }


def active_profile(args: argparse.Namespace) -> dict:
    prof = load_profile(resolve_profile_name(args))
    # 全コマンド冒頭で「いまどの顧客か」を明示 (gh auth status 相当)
    print(f"[profile={prof['name']} account={prof['account_id']} region={prof['region']}]",
          file=sys.stderr)
    return prof


# ---------- 監査ログ (ADR §E) ----------

def audit(prof: dict, cmd: str, status: str, latency_ms: int | None = None,
          nrql: str | None = None):
    """~/.newrelic/audit.log に JSONL 追記。鍵・生 NRQL は記録しない。"""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": prof["name"], "account_id": prof["account_id"],
        "region": prof["region"], "cmd": cmd, "status": status,
    }
    if latency_ms is not None:
        rec["latency_ms"] = latency_ms
    if nrql is not None:
        rec["nrql_sha256"] = hashlib.sha256(nrql.encode()).hexdigest()
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- NerdGraph client (throttle + backoff) ----------

class NerdGraph:
    def __init__(self, prof: dict, args: argparse.Namespace):
        self.prof = prof
        self.endpoint = REGIONS[prof["region"]]["graphql"]
        self.min_interval = int(cfg(args, "min_interval_ms")) / 1000.0
        self.max_retries = int(cfg(args, "max_retries"))
        self.timeout = float(cfg(args, "timeout_s"))
        # 鍵は header のみ。argv にも環境変数 echo にも出さない (ADR §F)。
        self._http = httpx.Client(
            headers={"API-Key": prof["api_key"], "Content-Type": "application/json"},
            timeout=self.timeout,
        )

    def close(self):
        self._http.close()

    def _throttle(self):
        if self.min_interval <= 0:
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_path = STATE_DIR / "state.json"
        with state_path.open("a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                raw = f.read().strip()
                last = json.loads(raw).get("last_request_ts", 0.0) if raw else 0.0
                wait = self.min_interval - (time.time() - last)
                if wait > 0:
                    time.sleep(wait)
                f.seek(0)
                f.truncate()
                f.write(json.dumps({"last_request_ts": time.time()}))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def query(self, query: str, variables: dict | None = None, soft: bool = False):
        """soft=True なら die せず None を返す (doctor が各チェックを継続できるように)。"""
        attempt = 0
        while True:
            self._throttle()
            try:
                r = self._http.post(self.endpoint,
                                    json={"query": query, "variables": variables or {}})
            except httpx.RequestError as e:
                if soft:
                    return None
                die(f"NerdGraph に接続できません ({self.endpoint}): {e}")
            if r.status_code == 429 or r.status_code >= 500:
                if attempt >= self.max_retries:
                    if soft:
                        return None
                    self._explain_and_die(r)
                retry_after = r.headers.get("Retry-After")
                delay = float(retry_after) if (retry_after and retry_after.isdigit()) \
                    else min(2 ** attempt, 30)
                delay += (time.time() % 1.0) * 0.5  # jitter (乱数依存を避ける)
                print(f"  ↻ {r.status_code} — {delay:.1f}s 待機して再試行 "
                      f"({attempt + 1}/{self.max_retries})", file=sys.stderr)
                time.sleep(delay)
                attempt += 1
                continue
            if r.status_code >= 400:
                if soft:
                    return None
                self._explain_and_die(r)
            body = r.json()
            if body.get("errors"):
                if soft:
                    return None
                msgs = "; ".join(e.get("message", str(e)) for e in body["errors"])
                die(f"NerdGraph エラー: {msgs}")
            return body["data"]

    def _explain_and_die(self, r: httpx.Response):
        hint = ""
        if r.status_code in (401, 403):
            hint = "\n  → API キー無効/権限不足の可能性。User Key (NRAK-*) とアカウント権限を確認。"
        elif r.status_code == 429:
            hint = "\n  → 同時25/user 制限。max_concurrency を下げるか時間をおいて再実行。"
        try:
            detail = json.dumps(r.json())[:300]
        except Exception:
            detail = r.text[:200]
        die(f"HTTP {r.status_code}: {detail}{hint}")


# ---------- queries ----------

Q_WHOAMI = "{ actor { user { id name email } } }"
Q_ACCOUNT = "query($id:Int!){ actor { account(id:$id){ id name } } }"
Q_NRQL = "query($id:Int!,$q:Nrql!){ actor { account(id:$id){ nrql(query:$q){ results } } } }"
Q_ENTITIES = ("query($q:String!){ actor { entitySearch(query:$q){ "
              "results { entities { guid name entityType reporting } } } } }")
Q_DASH = ("query($q:String!){ actor { entitySearch(query:$q){ "
          "results { entities { guid name } } } } }")


# ---------- subcommands ----------

def cmd_whoami(args):
    prof = active_profile(args)
    ng = NerdGraph(prof, args)
    t0 = time.time()
    try:
        user = ng.query(Q_WHOAMI)["actor"]["user"]
        acct = ng.query(Q_ACCOUNT, {"id": prof["account_id"]})["actor"]["account"]
    finally:
        ng.close()
    latency = int((time.time() - t0) * 1000)
    if not acct:
        audit(prof, "whoami", "account-invisible", latency)
        die(f"鍵は有効ですが account {prof['account_id']} を見られません (profile の "
            "account_id か鍵の権限を確認)")
    print(json.dumps({"user": user, "account": acct, "region": prof["region"]},
                     ensure_ascii=False, indent=2))
    audit(prof, "whoami", "ok", latency)


def cmd_doctor(args):
    """ADR §A: .mcp.json region == profile == 鍵が見える account の3者一致を検証。"""
    name = resolve_profile_name(args)
    prof = load_profile(name)
    print(f"[profile={prof['name']} account={prof['account_id']} region={prof['region']}]",
          file=sys.stderr)
    ok = True

    def check(label, passed, detail=""):
        nonlocal ok
        mark = "✓" if passed else "✗"
        print(f"  {mark} {label}{(': ' + detail) if detail else ''}")
        if not passed:
            ok = False

    # 1) 鍵が account を実際に見られるか (soft: 失敗してもチェックを継続)
    ng = NerdGraph(prof, args)
    try:
        data = ng.query(Q_ACCOUNT, {"id": prof["account_id"]}, soft=True)
    finally:
        ng.close()
    acct = (data or {}).get("actor", {}).get("account") if data else None
    check(f"鍵が account {prof['account_id']} を見られる", bool(acct),
          acct["name"] if acct else "見えない/鍵無効/接続不可")

    # 2) .mcp.json の region が profile と一致 (対話経路の誤爆防止)
    mcp = find_mcp_json()
    if mcp is None:
        if prof["mcp_allowed"]:
            check(".mcp.json 存在", False, "見つかりません (init で生成、または対話を使わないなら無視可)")
        else:
            print("  - .mcp.json: この profile は mcp_allowed=false (skill 専用)")
    else:
        server = mcp_server_entry(mcp)
        url = (server or {}).get("url", "")
        expected = REGIONS[prof["region"]]["mcp"]
        check(f".mcp.json の region URL が profile({prof['region']}) と一致",
              url.rstrip("/") == expected.rstrip("/"), url or "(url なし)")
        headers = (server or {}).get("headers", {})
        hardcoded = any("NRAK" in str(v).upper() or "${" not in str(v) for v in headers.values())
        check(".mcp.json が鍵を直書きせず env 参照", not hardcoded and bool(headers),
              "鍵が直書きされています" if hardcoded else "env 参照 OK")

    # 3) Claude Code が注入する $NEW_RELIC_API_KEY が profile の鍵と一致
    injected = os.environ.get("NEW_RELIC_API_KEY")
    if injected is None:
        check("$NEW_RELIC_API_KEY が現在の環境に存在 (MCP がこれを使う)", False,
              "未設定 (.envrc/direnv で profile を export してください)")
    else:
        check("$NEW_RELIC_API_KEY が profile の鍵と一致 (MCP と skill が同一顧客)",
              injected == prof["api_key"],
              "別の鍵が入っています (別顧客を指す恐れ)" if injected != prof["api_key"] else "一致")

    audit(prof, "doctor", "ok" if ok else "mismatch")
    print(("\nOK: 3者一致。MCP と skill は同じ顧客テナントを指します。" if ok
           else "\nNG: 不一致あり。上記 ✗ を解消するまで対話経路は使わないでください。"))
    sys.exit(0 if ok else 2)


def cmd_nrql(args):
    prof = active_profile(args)
    ng = NerdGraph(prof, args)
    t0 = time.time()
    try:
        data = ng.query(Q_NRQL, {"id": prof["account_id"], "q": args.query})
    finally:
        ng.close()
    latency = int((time.time() - t0) * 1000)
    results = data["actor"]["account"]["nrql"]["results"]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    audit(prof, "nrql", "ok", latency, nrql=args.query)


def cmd_entities(args):
    prof = active_profile(args)
    q = args.query or ""
    nrql_q = f"name LIKE '%{q}%'" if q else "reporting = 'true'"
    if args.type:
        nrql_q += f" AND type = '{args.type}'"
    ng = NerdGraph(prof, args)
    try:
        data = ng.query(Q_ENTITIES, {"q": nrql_q})
    finally:
        ng.close()
    ents = data["actor"]["entitySearch"]["results"]["entities"]
    print(json.dumps(ents, ensure_ascii=False, indent=2))
    audit(prof, "entities", "ok")


def cmd_dashboards(args):
    prof = active_profile(args)
    ng = NerdGraph(prof, args)
    try:
        data = ng.query(Q_DASH, {"q": f"type = 'DASHBOARD' AND accountId = {prof['account_id']}"})
    finally:
        ng.close()
    ents = data["actor"]["entitySearch"]["results"]["entities"]
    print(json.dumps(ents, ensure_ascii=False, indent=2))
    audit(prof, "dashboards", "ok")


def cmd_alerts(args):
    prof = active_profile(args)
    q = (f"query($id:Int!){{ actor {{ account(id:$id){{ alerts {{ "
         f"policiesSearch {{ policies {{ id name }} }} }} }} }} }}")
    ng = NerdGraph(prof, args)
    try:
        data = ng.query(q, {"id": prof["account_id"]})
    finally:
        ng.close()
    pol = data["actor"]["account"]["alerts"]["policiesSearch"]["policies"]
    print(json.dumps(pol, ensure_ascii=False, indent=2))
    audit(prof, "alerts", "ok")


def cmd_profile(args):
    if args.action == "list":
        if not PROFILE_DIR.exists():
            print("(profile なし。~/.newrelic/<名>.env を作成してください)")
            return
        for p in sorted(PROFILE_DIR.glob("*.env")):
            print(p.stem)  # 名前のみ (鍵・account は出さない)
    elif args.action == "path":
        print(PROFILE_DIR / f"{resolve_profile_name(args)}.env")
    elif args.action == "show":
        prof = load_profile(resolve_profile_name(args))
        print(json.dumps({"name": prof["name"], "account_id": prof["account_id"],
                          "region": prof["region"], "mcp_allowed": prof["mcp_allowed"]},
                         ensure_ascii=False, indent=2))  # 鍵は出さない


# ---------- per-project MCP 関連 ----------

def find_mcp_json() -> Path | None:
    for cand in (Path.cwd() / ".mcp.json", Path.cwd() / ".claude" / "settings.json"):
        if cand.exists():
            return cand
    return None


def mcp_server_entry(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    return (data.get("mcpServers") or {}).get("newrelic")


def cmd_init(args):
    target = Path(args.dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    name = (args.profile or "").strip()
    if not name:
        die("init には --profile <名> が必要です")
    prof = load_profile(name)  # 存在・検証 (無ければここで失敗)

    # .newrelic-profile (repo ローカル・commit しない)
    (target / ".newrelic-profile").write_text(name + "\n")

    # .gitignore に必須エントリ追加 (顧客名/鍵の漏洩防止; ADR §D/§F)
    gi = target / ".gitignore"
    want = [".newrelic-profile", ".envrc", "*.nrql.local"]
    existing = gi.read_text().splitlines() if gi.exists() else []
    add = [w for w in want if w not in existing]
    if add:
        with gi.open("a") as f:
            if existing and existing[-1].strip():
                f.write("\n")
            f.write("# New Relic (顧客名/鍵の漏洩防止)\n" + "\n".join(add) + "\n")

    # .envrc (direnv: .newrelic-profile の profile を自動 export → MCP の env バインド)
    envrc = target / ".envrc"
    if not envrc.exists():
        envrc.write_text(
            'set -a\n'
            'source "$HOME/.newrelic/$(cat .newrelic-profile).env"\n'
            'set +a\n')
        print("  .envrc を生成しました。`direnv allow` で有効化してください", file=sys.stderr)

    # .mcp.json 生成 (mcp_allowed=false の profile はスキップ)
    if not prof["mcp_allowed"]:
        print("  この profile は mcp_allowed=false → .mcp.json は生成しません (skill 専用)",
              file=sys.stderr)
    else:
        mcp_path = target / ".mcp.json"
        data = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
        servers = data.setdefault("mcpServers", {})
        servers["newrelic"] = {
            "type": "http",
            "url": REGIONS[prof["region"]]["mcp"],
            # 鍵は直書きせず env 参照。ヘッダ名は NR の MCP セットアップ手順で要確認 (検証項目)。
            "headers": {"API-Key": "${NEW_RELIC_API_KEY}"},
        }
        mcp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(f"  .mcp.json を生成 (region={prof['region']}, url={REGIONS[prof['region']]['mcp']})",
              file=sys.stderr)

    print(f"init 完了: {target} (profile={name})")
    print("次: `direnv allow` → `/newrelic doctor` で3者一致を検証してください")


# ---------- argparse ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="newrelic", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    # 共通オプションは parent に置き各サブコマンドへ継承 (サブコマンドの後でも拾えるように)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="使う profile 名 (省略時は .newrelic-profile)")
    common.add_argument("--max-concurrency", dest="max_concurrency", type=int)
    common.add_argument("--min-interval-ms", dest="min_interval_ms", type=int)
    common.add_argument("--max-retries", dest="max_retries", type=int)
    common.add_argument("--timeout-s", dest="timeout_s", type=float)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", parents=[common],
                   help="鍵が見える account/region を表示").set_defaults(func=cmd_whoami)
    sub.add_parser("doctor", parents=[common], help="3者一致検証").set_defaults(func=cmd_doctor)

    sp = sub.add_parser("nrql", parents=[common], help="NRQL 実行")
    sp.add_argument("query", help="NRQL 文字列")
    sp.set_defaults(func=cmd_nrql)

    sp = sub.add_parser("entities", parents=[common], help="エンティティ検索")
    sp.add_argument("--query", help="名前部分一致")
    sp.add_argument("--type", help="entity type (例: APPLICATION)")
    sp.set_defaults(func=cmd_entities)

    sp = sub.add_parser("dashboards", parents=[common], help="ダッシュボード一覧")
    sp.add_argument("action", nargs="?", default="list", choices=["list"])
    sp.set_defaults(func=cmd_dashboards)

    sp = sub.add_parser("alerts", parents=[common], help="アラートポリシー参照")
    sp.add_argument("action", nargs="?", default="list", choices=["list", "policies"])
    sp.set_defaults(func=cmd_alerts)

    sp = sub.add_parser("profile", parents=[common], help="profile 一覧/表示")
    sp.add_argument("action", choices=["list", "show", "path"])
    sp.set_defaults(func=cmd_profile)

    sp = sub.add_parser("init", parents=[common], help="per-project 雛形展開")
    sp.add_argument("dir", nargs="?", default=".")
    sp.set_defaults(func=cmd_init)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
