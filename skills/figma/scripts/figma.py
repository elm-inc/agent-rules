#!/usr/bin/env python3
"""figma — rate-limit-aware Figma REST client.

Figma の REST API は cost ベースのレート制限で、超過時に 429 + Retry-After を返す。
このスクリプトは「無駄な API 呼び出しを構造的に減らす」ための制御を一手に引き受ける:

  1. version 差分キャッシュ  — 軽量な ?depth=1 で file version を取り、同一 version の
                               結果はディスクから返す (フル取得をスキップ)。
  2. version-check TTL       — 短時間 (既定 60s) 内は version チェック自体も省略。
  3. ローカルスロットル      — fcntl ロックで全プロセス共有の最小送信間隔を保つ
                               (worktree 並列でも安全)。
  4. 429 バックオフ          — Retry-After 準拠 + 指数 + jitter で自動リトライ。
  5. 部分取得 / バッチ       — ids/depth で必要枝だけ、images は複数 id を 1 リクエストに。

Subcommands:
  me                 接続確認 (GET /v1/me, 安価)
  file    <key|url>  ファイル取得 (version 差分キャッシュ)。既定は要約表示、--out で全 JSON
  nodes   <key|url>  --ids で指定ノードだけ部分取得
  images  <key|url>  --ids を 1 リクエストでバッチレンダー & ダウンロード (png/svg/pdf/jpg)
  tokens  <key|url>  Variables/Styles を design tokens として抽出 (Enterprise 無ければ Styles)
  comments <key|url> コメント一覧
  parse-url <url>    Figma URL から file key と node-id を抽出
  cache   status     キャッシュ統計と「節約できたリクエスト数」を表示
  cache   clear      キャッシュ削除 (--key で特定ファイルのみ)

設定の解決順: コマンドライン引数 > 環境変数 > ~/.config/figma.toml > 既定値
token の解決順: --token > $FIGMA_TOKEN > ~/.figma_token
cache dir:    $FIGMA_CACHE_DIR > ~/.cache/figma
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27", "tomli; python_version<'3.11'"]
# ///

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

import httpx

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

API = "https://api.figma.com"
CONFIG_PATH = Path.home() / ".config" / "figma.toml"
TOKEN_FILE = Path.home() / ".figma_token"

DEFAULTS = {
    "min_interval_ms": 600,   # 全プロセス共有の最小送信間隔 (≈100 req/min)。429 を避ける床
    "version_ttl_s": 60,      # この秒数内は file version の再チェックを省略
    "max_retries": 4,         # 429/5xx のリトライ上限
    "timeout_s": 60,
}


# ---------- config / token ----------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    return {}


def cfg(args: argparse.Namespace, key: str):
    val = getattr(args, key, None)
    if val is not None:
        return val
    env = os.environ.get(f"FIGMA_{key.upper()}")
    if env is not None:
        return type(DEFAULTS[key])(env) if key in DEFAULTS else env
    c = load_config()
    if key in c:
        return c[key]
    return DEFAULTS.get(key)


def resolve_token(args: argparse.Namespace) -> str:
    if getattr(args, "token", None):
        return args.token
    if os.environ.get("FIGMA_TOKEN"):
        return os.environ["FIGMA_TOKEN"]
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    die("Figma token が見つかりません (--token / $FIGMA_TOKEN / ~/.figma_token のいずれかが必要)")


def cache_dir() -> Path:
    d = Path(os.environ.get("FIGMA_CACHE_DIR", str(Path.home() / ".cache" / "figma")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def log_event(event: dict):
    """requests.log (JSONL) に 1 行追記。cache status の集計元。"""
    event["ts"] = time.time()
    line = json.dumps(event, ensure_ascii=False)
    with (cache_dir() / "requests.log").open("a") as f:
        f.write(line + "\n")


# ---------- URL / key parsing ----------

_KEY_RE = re.compile(r"/(?:file|design|proto)/([A-Za-z0-9]+)")


def parse_target(s: str) -> tuple[str, list[str]]:
    """'key' か Figma URL を受け取り (file_key, node_ids) を返す。

    URL の node-id は '1-2' / '1%3A2' 形式で来るので API が期待する '1:2' へ正規化。
    """
    if "figma.com" in s:
        m = _KEY_RE.search(urlparse(s).path)
        if not m:
            die(f"URL から file key を抽出できませんでした: {s}")
        key = m.group(1)
        node_ids: list[str] = []
        qs = parse_qs(urlparse(s).query)
        if "node-id" in qs:
            node_ids = [unquote(n).replace("-", ":") for n in qs["node-id"]]
        return key, node_ids
    return s, []


def norm_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [i.strip().replace("-", ":") for i in raw.split(",") if i.strip()]


# ---------- HTTP core (throttle + backoff) ----------

class Client:
    def __init__(self, args: argparse.Namespace):
        self.token = resolve_token(args)
        self.min_interval = int(cfg(args, "min_interval_ms")) / 1000.0
        self.max_retries = int(cfg(args, "max_retries"))
        self.timeout = float(cfg(args, "timeout_s"))
        self._http = httpx.Client(
            headers={"X-Figma-Token": self.token},
            timeout=self.timeout,
            follow_redirects=True,
        )

    def _throttle(self):
        """state.json の last_request_ts を fcntl ロック下で読み書きし、最小間隔を保つ。

        ロックは sleep を含めて保持するので、並列プロセスは順番待ちになる
        (worktree 並列でも合計送信レートが床を超えない)。
        """
        state_path = cache_dir() / "state.json"
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

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        url = f"{API}{path}"
        attempt = 0
        while True:
            self._throttle()
            r = self._http.get(url, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt >= self.max_retries:
                    log_event({"event": "request", "path": path, "status": r.status_code,
                               "gave_up": True})
                    self._explain_and_die(r, path)
                retry_after = r.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = min(2 ** attempt, 30)
                # 指数 + jitter (時刻ベースの軽い擾乱; 乱数依存を避ける)
                jitter = (time.time() % 1.0) * 0.5
                delay += jitter
                log_event({"event": "retry", "path": path, "status": r.status_code,
                           "attempt": attempt, "sleep_s": round(delay, 2)})
                print(f"  ↻ {r.status_code} — {delay:.1f}s 待機して再試行 "
                      f"({attempt + 1}/{self.max_retries})", file=sys.stderr)
                time.sleep(delay)
                attempt += 1
                continue
            log_event({"event": "request", "path": path, "status": r.status_code,
                       "bytes": len(r.content), "cache": "miss"})
            if r.status_code >= 400:
                self._explain_and_die(r, path)
            return r

    def download(self, url: str) -> bytes:
        """S3 等の画像 URL を取得。Figma API の rate budget 対象外なので throttle しない。"""
        r = self._http.get(url)
        r.raise_for_status()
        return r.content

    def _explain_and_die(self, r: httpx.Response, path: str):
        hint = ""
        if r.status_code == 403:
            hint = ("\n  → PAT のスコープ不足の可能性。Figma の token 設定で "
                    "file_content:read / file_comments:read / file_variables:read 等を確認。")
        elif r.status_code == 404:
            hint = "\n  → file key が誤りか、その PAT でアクセス権が無いファイルの可能性。"
        elif r.status_code == 429:
            hint = "\n  → レート制限。時間をおくか min_interval_ms を上げて再実行。"
        try:
            body = r.json()
            detail = body.get("err") or body.get("message") or json.dumps(body)
        except Exception:
            detail = r.text[:200]
        die(f"{path} → HTTP {r.status_code}: {detail}{hint}")


# ---------- version-aware cache ----------

def _params_hash(parts: dict) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def get_version(client: Client, key: str, ttl: float, force: bool) -> str:
    """軽量な ?depth=1 で file version を取得。TTL 内なら API を叩かず前回値を返す。"""
    vpath = cache_dir() / "versions" / f"{key}.json"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    if not force and vpath.exists():
        rec = json.loads(vpath.read_text())
        if time.time() - rec["checked_at"] < ttl:
            log_event({"event": "version", "key": key, "cache": "ttl-skip"})
            return rec["version"]
    r = client.get(f"/v1/files/{key}", params={"depth": 1})
    version = r.json().get("version", "0")
    vpath.write_text(json.dumps({"version": version, "checked_at": time.time()}))
    return version


def cache_get(key: str, version: str, kind: str, phash: str) -> Path | None:
    p = cache_dir() / kind / f"{key}-{version}-{phash}.json"
    return p if p.exists() else None


def cache_put(key: str, version: str, kind: str, phash: str, data) -> Path:
    p = cache_dir() / kind / f"{key}-{version}-{phash}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False))
    return p


def fetch_cached(client: Client, args, key: str, kind: str, path: str,
                 params: dict, cache_parts: dict):
    """version 差分キャッシュ付き GET。(data, hit:bool, version) を返す。"""
    if getattr(args, "no_cache", False):
        return client.get(path, params=params).json(), False, None
    ttl = float(cfg(args, "version_ttl_s"))
    version = get_version(client, key, ttl, getattr(args, "force", False))
    phash = _params_hash(cache_parts)
    hit = cache_get(key, version, kind, phash)
    if hit and not getattr(args, "force", False):
        log_event({"event": "cache_hit", "key": key, "kind": kind, "version": version})
        return json.loads(hit.read_text()), True, version
    data = client.get(path, params=params).json()
    cache_put(key, version, kind, phash, data)
    return data, False, version


# ---------- summaries (token 節約のため既定は要約表示) ----------

def summarize_document(doc: dict) -> list[str]:
    lines = []
    for page in doc.get("children", []):
        lines.append(f"  ▸ {page.get('name','?')}  [{page.get('type')}]  id={page.get('id')}")
        for child in page.get("children", [])[:50]:
            lines.append(f"      - {child.get('name','?')}  "
                         f"[{child.get('type')}]  id={child.get('id')}")
    return lines


# ---------- subcommands ----------

def cmd_me(client: Client, args):
    me = client.get("/v1/me").json()
    print(json.dumps({k: me.get(k) for k in ("id", "email", "handle")},
                     ensure_ascii=False, indent=2))


def cmd_file(client: Client, args):
    key, url_ids = parse_target(args.target)
    params = {}
    if args.depth is not None:
        params["depth"] = args.depth
    if args.geometry:
        params["geometry"] = "paths"
    data, hit, version = fetch_cached(
        client, args, key, "file", f"/v1/files/{key}", params,
        {"depth": args.depth, "geometry": bool(args.geometry)})
    src = "cache" if hit else "api"
    if args.out:
        Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"[{src}] {key} v={version} → {args.out} "
              f"({len(json.dumps(data))} bytes)")
    elif args.json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(f"[{src}] {data.get('name','?')}  v={version}")
        print("\n".join(summarize_document(data.get("document", {}))))
        print("\n(全 JSON は --out FILE / 生出力は --json)")


def cmd_nodes(client: Client, args):
    key, url_ids = parse_target(args.target)
    ids = norm_ids(args.ids) or url_ids
    if not ids:
        die("--ids か node-id 付き URL が必要です")
    params = {"ids": ",".join(ids)}
    if args.depth is not None:
        params["depth"] = args.depth
    if args.geometry:
        params["geometry"] = "paths"
    data, hit, version = fetch_cached(
        client, args, key, "nodes", f"/v1/files/{key}/nodes", params,
        {"ids": sorted(ids), "depth": args.depth, "geometry": bool(args.geometry)})
    src = "cache" if hit else "api"
    if args.out:
        Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"[{src}] {key} v={version} nodes={len(ids)} → {args.out}")
    elif args.json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(f"[{src}] {key}  v={version}  nodes={len(ids)}")
        for nid, wrap in data.get("nodes", {}).items():
            doc = (wrap or {}).get("document", {})
            print(f"  ▸ {doc.get('name','?')}  [{doc.get('type')}]  id={nid}  "
                  f"children={len(doc.get('children', []))}")


def cmd_images(client: Client, args):
    key, url_ids = parse_target(args.target)
    ids = norm_ids(args.ids) or url_ids
    if not ids:
        die("--ids か node-id 付き URL が必要です")
    out_dir = Path(args.out_dir or "figma-export")
    out_dir.mkdir(parents=True, exist_ok=True)
    ttl = float(cfg(args, "version_ttl_s"))
    version = "nocache" if args.no_cache else get_version(client, key, ttl, args.force)

    # version 別にダウンロード済みファイルがあれば render 自体をスキップ
    cached_files, need = {}, []
    for nid in ids:
        safe = nid.replace(":", "-")
        f = out_dir / f"{safe}.{args.format}"
        marker = cache_dir() / "images" / f"{key}-{version}-{safe}-{args.format}-{args.scale}"
        if not args.no_cache and not args.force and marker.exists() and f.exists():
            cached_files[nid] = f
        else:
            need.append((nid, safe, f, marker))

    if need:
        params = {"ids": ",".join(n[0] for n in need), "format": args.format}
        if args.format in ("png", "jpg"):
            params["scale"] = args.scale
        resp = client.get(f"/v1/images/{key}", params=params).json()
        if resp.get("err"):
            die(f"images render error: {resp['err']}")
        urls = resp.get("images", {})
        for nid, safe, f, marker in need:
            u = urls.get(nid)
            if not u:
                print(f"  ! {nid}: レンダー URL が返りませんでした (空フレーム?)",
                      file=sys.stderr)
                continue
            f.write_bytes(client.download(u))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("1")
            print(f"  ↓ {f}")

    for nid, f in cached_files.items():
        print(f"  = {f} (cache)")
    print(f"[done] {len(cached_files)} cached + {len(need)} fetched → {out_dir}/  "
          f"(v={version})")


def cmd_tokens(client: Client, args):
    key, _ = parse_target(args.target)
    tokens: dict = {"variables": {}, "styles": {}}
    # 1) Variables (Enterprise + file_variables:read が必要)。無ければ静かに Styles へ。
    try:
        r = client.get(f"/v1/files/{key}/variables/local")
        vdata = r.json().get("meta", {})
        for vid, v in vdata.get("variables", {}).items():
            tokens["variables"][v.get("name", vid)] = {
                "type": v.get("resolvedType"),
                "values": v.get("valuesByMode"),
            }
    except SystemExit:
        print("  (variables endpoint 利用不可 — Enterprise/scope 無し。Styles のみ抽出)",
              file=sys.stderr)
    # 2) ファイル内ローカルスタイル
    data, hit, version = fetch_cached(
        client, args, key, "file", f"/v1/files/{key}", {},
        {"depth": None, "geometry": False})
    for sid, s in data.get("styles", {}).items():
        tokens["styles"][s.get("name", sid)] = {"type": s.get("styleType")}
    out = args.out or f"figma-tokens-{key}.json"
    Path(out).write_text(json.dumps(tokens, ensure_ascii=False, indent=2))
    print(f"tokens → {out}  (variables={len(tokens['variables'])}, "
          f"styles={len(tokens['styles'])})")


def cmd_comments(client: Client, args):
    key, _ = parse_target(args.target)
    data = client.get(f"/v1/files/{key}/comments").json()
    comments = data.get("comments", [])
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
        return
    print(f"{len(comments)} comments")
    for c in comments:
        who = (c.get("user") or {}).get("handle", "?")
        msg = (c.get("message") or "").replace("\n", " ")[:80]
        print(f"  [{c.get('created_at','')[:10]}] {who}: {msg}")


def cmd_parse_url(client, args):
    key, ids = parse_target(args.target)
    print(json.dumps({"file_key": key, "node_ids": ids}, ensure_ascii=False, indent=2))


def cmd_cache(client, args):
    cd = cache_dir()
    if args.cache_cmd == "clear":
        import shutil
        if args.key:
            removed = 0
            for kind in ("file", "nodes", "versions", "images"):
                for p in (cd / kind).glob(f"{args.key}*"):
                    p.unlink()
                    removed += 1
            print(f"removed {removed} entries for {args.key}")
        else:
            for kind in ("file", "nodes", "versions", "images"):
                shutil.rmtree(cd / kind, ignore_errors=True)
            (cd / "requests.log").unlink(missing_ok=True)
            print(f"cleared cache at {cd}")
        return

    # status
    def dir_size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0

    print(f"cache dir: {cd}  ({dir_size(cd) / 1024:.0f} KiB)")
    for kind in ("file", "nodes", "images", "versions"):
        n = len(list((cd / kind).glob("*"))) if (cd / kind).exists() else 0
        print(f"  {kind:9} entries: {n}")

    log = cd / "requests.log"
    if not log.exists():
        print("\n(no request log yet)")
        return
    n_req = n_hit = n_skip = n_retry = 0
    for line in log.read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        ev = e.get("event")
        if ev == "request":
            n_req += 1
        elif ev == "cache_hit":
            n_hit += 1
        elif ev == "version" and e.get("cache") == "ttl-skip":
            n_skip += 1
        elif ev == "retry":
            n_retry += 1
    saved = n_hit + n_skip
    total = n_req + saved
    rate = (saved / total * 100) if total else 0
    print(f"\nlifetime: {n_req} API requests sent")
    print(f"  saved by cache:   {n_hit} full fetches")
    print(f"  saved by TTL:     {n_skip} version checks")
    print(f"  429/5xx retries:  {n_retry}")
    print(f"  → {saved} requests avoided ({rate:.0f}% of would-be calls)")


# ---------- argparse ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="figma", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--token", help="PAT (既定: $FIGMA_TOKEN > ~/.figma_token)")
    p.add_argument("--min-interval-ms", dest="min_interval_ms", type=int,
                   help="最小送信間隔 (既定 600)")
    p.add_argument("--version-ttl-s", dest="version_ttl_s", type=int,
                   help="version 再チェック省略 TTL 秒 (既定 60)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp, target=True):
        if target:
            sp.add_argument("target", help="file key または Figma URL")
        sp.add_argument("--no-cache", action="store_true", help="キャッシュを使わない")
        sp.add_argument("--force", action="store_true", help="version を再取得し再フェッチ")
        sp.add_argument("--json", action="store_true", help="生 JSON を stdout へ")

    sp = sub.add_parser("me"); sp.set_defaults(func=cmd_me)

    sp = sub.add_parser("file"); add_common(sp)
    sp.add_argument("--depth", type=int, help="ツリー深さ制限 (浅いほど安価)")
    sp.add_argument("--geometry", action="store_true", help="ベクタ geometry を含める")
    sp.add_argument("--out", help="全 JSON を書き出すファイル")
    sp.set_defaults(func=cmd_file)

    sp = sub.add_parser("nodes"); add_common(sp)
    sp.add_argument("--ids", help="カンマ区切り node-id")
    sp.add_argument("--depth", type=int)
    sp.add_argument("--geometry", action="store_true")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_nodes)

    sp = sub.add_parser("images"); add_common(sp)
    sp.add_argument("--ids", help="カンマ区切り node-id")
    sp.add_argument("--format", default="png", choices=["png", "svg", "pdf", "jpg"])
    sp.add_argument("--scale", default="2", help="png/jpg の倍率 (既定 2)")
    sp.add_argument("--out-dir", help="保存先 (既定 figma-export/)")
    sp.set_defaults(func=cmd_images)

    sp = sub.add_parser("tokens"); add_common(sp)
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_tokens)

    sp = sub.add_parser("comments"); add_common(sp)
    sp.set_defaults(func=cmd_comments)

    sp = sub.add_parser("parse-url")
    sp.add_argument("target", help="Figma URL")
    sp.set_defaults(func=cmd_parse_url)

    sp = sub.add_parser("cache")
    sp.add_argument("cache_cmd", choices=["status", "clear"])
    sp.add_argument("--key", help="clear 時に特定ファイルキーのみ削除")
    sp.set_defaults(func=cmd_cache)

    return p


def main() -> int:
    args = build_parser().parse_args()
    # parse-url / cache は API 不要
    if args.cmd in ("parse-url", "cache"):
        args.func(None, args)
        return 0
    client = Client(args)
    with contextlib.closing(client._http):
        args.func(client, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
