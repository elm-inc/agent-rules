#!/usr/bin/env python3
"""ポート利用状況の棚卸し (live + 宣言 + 予約台帳)。

複数案件を並行開発していると「どの案件がどのポートか」が分からなくなる。
本スクリプトは 3 つの情報源を突き合わせて、ポートに案件名を付ける:

  1. live/docker   … docker compose のラベルから repo 絶対パスを取る (確定)
  2. live/process  … ss で自分が持つ LISTEN → /proc/<pid>/cwd → git root (確定)
  3. 宣言          … compose / vite / package.json / .env のポート記述 (best-effort)

`ss` で読めるのは自分が所有するプロセスだけで、docker が publish した
ポートは root 所有の docker-proxy になる (実測: LISTEN 110 件中 14 件しか
プロセス名が取れない)。よって docker 側の情報が無いと大半が attribution
不能になる — この突き合わせが本スクリプトの本体。

台帳 (任意) は ~/.config/agent-rules/ports.yml。agent-rules は public repo
なので、案件名を含む台帳は repo に置かない (ADR-0018)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_PATH = Path(
    os.environ.get("AGENT_RULES_PORT_REGISTRY", Path.home() / ".config/agent-rules/ports.yml")
)
REPOS_ROOT = Path(os.environ.get("AGENT_RULES_REPOS_ROOT", Path.home() / "repos"))

# 宣言スキャンの対象。node_modules 等は除外する
SCAN_GLOBS = [
    "**/compose*.yml", "**/compose*.yaml",
    "**/docker-compose*.yml", "**/docker-compose*.yaml",
    "**/vite.config.*", "**/package.json", "**/.env", "**/.env.*",
]
SCAN_EXCLUDES = [
    "!**/node_modules/**", "!**/.venv/**", "!**/venv/**", "!**/dist/**",
    "!**/build/**", "!**/.next/**", "!**/target/**", "!**/vendor/**",
]

# 情報源が使えなかった理由。黙って「0 件 = 衝突なし」と見せないために集める
# (検知機構が壊れたら成功扱いにしない = fail-close)
SOURCE_ISSUES: list[str] = []

# "${FOO:-5432}" / "${FOO}" / "5432" のいずれからも数値を取り出す
VAR_DEFAULT_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
PORT_NUM_RE = re.compile(r"^\d{1,5}$")


# --------------------------------------------------------------------------
# データモデル
# --------------------------------------------------------------------------


@dataclass
class Live:
    """いま実際に LISTEN しているポート 1 件。"""

    port: int
    bind: str
    source: str  # docker | process | unattributed
    project: str | None = None
    repo: Path | None = None
    detail: str = ""


@dataclass
class Declared:
    """設定ファイルに書かれたポート 1 件 (停止中でも分かる)。

    kind の区別が重要:
      bind … compose の ports: ホスト側 / vite の server.port / --port
             = 起動時にホストのそのポートを実際に確保する。衝突判定の対象
      hint … .env の *PORT=  = 多くは「接続先」であって確保ではない
             (DB_PORT=5432 は docker ネットワーク内の postgres を指すだけ)。
             ここを衝突判定に混ぜると 5432/3306/6379 が全案件で誤検出になる
    """

    port: int
    project: str
    repo: Path
    origin: str  # "compose.yaml:14" のような出所
    var: str | None = None  # ${AINAVICE_DB_PORT:-55433} の変数名
    kind: str = "bind"


@dataclass
class Registry:
    """~/.config/agent-rules/ports.yml の内容。無くても動く。"""

    path: Path
    exists: bool = False
    projects: dict[str, dict] = field(default_factory=dict)

    def range_of(self, project: str) -> tuple[int, int] | None:
        """台帳の帯を返す。人が手で書く YAML なので不正値で落とさない。"""
        entry = self.projects.get(project)
        if not isinstance(entry, dict):
            return None
        rng = entry.get("range")
        if rng is None:
            return None
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            SOURCE_ISSUES.append(f"台帳の {project}.range は [開始, 終了] で書いてください: {rng!r}")
            return None
        try:
            lo, hi = int(rng[0]), int(rng[1])
        except (TypeError, ValueError):
            SOURCE_ISSUES.append(f"台帳の {project}.range に数値でない値があります: {rng!r}")
            return None
        if lo > hi:
            SOURCE_ISSUES.append(f"台帳の {project}.range の開始 > 終了 です: {rng!r}")
            return None
        return lo, hi


# --------------------------------------------------------------------------
# repo / プロジェクト解決
# --------------------------------------------------------------------------


_repo_cache: dict[str, Path | None] = {}


def git_main_worktree(start: Path) -> Path | None:
    """パスを含む git リポジトリの「メインワークツリー」を返す。

    worktree で作業していても案件名がブレないよう、--git-common-dir から
    メイン側を復元する (例: foo-worktrees/bar → foo)。
    """
    key = str(start)
    if key in _repo_cache:
        return _repo_cache[key]

    result: Path | None = None
    if start.is_dir():
        try:
            proc = subprocess.run(
                ["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                common = Path(proc.stdout.strip())
                # <repo>/.git → <repo>  /  bare や worktree 管理下でも親を採る
                result = common.parent if common.name == ".git" else common
        except (OSError, subprocess.SubprocessError):
            result = None
    _repo_cache[key] = result
    return result


def project_name(repo: Path | None) -> str | None:
    return repo.name if repo else None


# --------------------------------------------------------------------------
# live: docker
# --------------------------------------------------------------------------


def docker_live() -> list[Live]:
    """docker が publish しているホスト側ポートを、compose ラベルで案件に紐付ける。"""
    if not shutil.which("docker"):
        SOURCE_ISSUES.append("docker が見つからないため、コンテナ由来のポートは調べていません")
        return []
    try:
        ids = subprocess.run(
            ["docker", "ps", "-q"], capture_output=True, text=True, timeout=20
        )
        if ids.returncode != 0:
            SOURCE_ISSUES.append(
                "docker ps に失敗したため、コンテナ由来のポートは調べていません "
                "(daemon 停止 or 権限不足)"
            )
            return []
        if not ids.stdout.strip():
            return []  # 起動中コンテナが 0 個。これは正常な「無し」
        proc = subprocess.run(
            ["docker", "inspect", *ids.stdout.split()],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            SOURCE_ISSUES.append("docker inspect に失敗したため、コンテナ由来のポートは調べていません")
            return []
        containers = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        SOURCE_ISSUES.append(f"docker の情報を取得できませんでした ({type(exc).__name__})")
        return []

    out: list[Live] = []
    for c in containers:
        labels = (c.get("Config") or {}).get("Labels") or {}
        name = (c.get("Name") or "").lstrip("/")
        compose_project = labels.get("com.docker.compose.project")
        workdir = labels.get("com.docker.compose.project.working_dir")
        repo = git_main_worktree(Path(workdir)) if workdir else None
        proj = project_name(repo) or compose_project
        inferred = False
        if proj is None:
            # `docker run` 直起動には compose ラベルが無い。コンテナ名から
            # repo 名を推測するが、推測であることを表示側に伝える (~ を付ける)
            proj = infer_project_from_name(name)
            inferred = proj is not None

        ports = ((c.get("NetworkSettings") or {}).get("Ports") or {})
        for container_port, bindings in ports.items():
            for b in bindings or []:
                host_port = b.get("HostPort")
                if not host_port:
                    continue
                out.append(Live(
                    port=int(host_port),
                    bind=b.get("HostIp") or "0.0.0.0",
                    source="docker",
                    project=(f"{proj} ~" if inferred else proj),
                    repo=repo,
                    detail=f"{name} → {container_port}",
                ))
    return out


_repo_names_cache: list[tuple[str, str]] | None = None


def known_repo_names() -> list[tuple[str, str]]:
    """~/repos 配下の (正規化名, 実名) 一覧。推測マッチ用。"""
    global _repo_names_cache
    if _repo_names_cache is None:
        names: list[tuple[str, str]] = []
        if REPOS_ROOT.is_dir():
            for host in REPOS_ROOT.iterdir():
                if not host.is_dir():
                    continue
                for org in host.iterdir():
                    if not org.is_dir():
                        continue
                    for repo in org.iterdir():
                        if repo.is_dir() and not repo.name.endswith("-worktrees"):
                            names.append((normalize(repo.name), repo.name))
        # 長い名前を先に見る (sega-pos-api が sega-pos より先にマッチするように)
        names.sort(key=lambda x: -len(x[0]))
        _repo_names_cache = names
    return _repo_names_cache


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def infer_project_from_name(container_name: str) -> str | None:
    """コンテナ名の先頭が repo 名と一致すれば、その案件と推測する。"""
    norm = normalize(container_name)
    for repo_norm, repo_real in known_repo_names():
        if len(repo_norm) >= 4 and norm.startswith(repo_norm):
            return repo_real
    return None


# --------------------------------------------------------------------------
# live: 素のプロセス (ss)
# --------------------------------------------------------------------------


SS_USERS_RE = re.compile(r'\(\("(?P<name>[^"]+)",pid=(?P<pid>\d+)')


def ss_live() -> list[Live]:
    """ss の LISTEN 一覧を読む。プロセス情報が取れるのは自分が所有するものだけ。"""
    if not shutil.which("ss"):
        SOURCE_ISSUES.append("ss が見つからないため、素のプロセス由来のポートは調べていません")
        return []
    try:
        proc = subprocess.run(
            ["ss", "-tlnpH"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError) as exc:
        SOURCE_ISSUES.append(f"ss を実行できませんでした ({type(exc).__name__})")
        return []
    if proc.returncode != 0:
        SOURCE_ISSUES.append("ss が異常終了したため、素のプロセス由来のポートは調べていません")
        return []

    out: list[Live] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        if ":" not in local:
            continue
        bind, _, port_s = local.rpartition(":")
        if not PORT_NUM_RE.match(port_s):
            continue

        m = SS_USERS_RE.search(line)
        if not m:
            # root 所有 (docker-proxy 等)。docker 側の結果で埋まる想定
            out.append(Live(port=int(port_s), bind=bind, source="unattributed"))
            continue

        pid = int(m.group("pid"))
        cwd, stale = read_proc_cwd(pid)
        repo = git_main_worktree(cwd) if cwd else None
        if repo is None:
            repo = repo_from_cmdline(pid)
        detail = f"{m.group('name')} (pid={pid})"
        if stale:
            detail += " ※削除済み worktree で稼働中"
        out.append(Live(
            port=int(port_s),
            bind=bind,
            source="process",
            project=project_name(repo),
            repo=repo,
            detail=detail,
        ))
    return out


def read_proc_cwd(pid: int) -> tuple[Path | None, bool]:
    """(作業ディレクトリ, cwd が消えているか) を返す。

    削除済み worktree で動き続けている dev server は cwd が "... (deleted)" に
    なる。これは「消したはずの worktree のプロセスが残っている」という有用な
    情報なので、握りつぶさず stale フラグとして返す。
    """
    try:
        target = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None, False
    stale = target.endswith(" (deleted)")
    path = Path(re.sub(r" \(deleted\)$", "", target))
    if path.is_dir():
        return path, stale
    return None, stale


PROC_PATH_RE = re.compile(r"(/home/[^\s:]+|/opt/[^\s:]+|/srv/[^\s:]+)")


def repo_from_cmdline(pid: int) -> Path | None:
    """cwd が消えているときの代替。コマンドラインに出てくるパスから repo を辿る。

    削除済み worktree はディレクトリ自体が無いので、`<repo>-worktrees/<タスク>`
    という本リポの規約 (CLAUDE.md §並列開発) を使って本体側へ写像する。
    """
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return None

    for m in PROC_PATH_RE.finditer(raw):
        candidate = Path(m.group(1))
        main = main_repo_of_worktree_path(candidate)
        if main is not None:
            return main
        # 実在する祖先まで遡って git repo を探す (存在しない階層は飛ばす)
        while candidate != candidate.parent:
            if candidate.is_dir():
                repo = git_main_worktree(candidate)
                if repo is not None:
                    return repo
            candidate = candidate.parent
    return None


def main_repo_of_worktree_path(path: Path) -> Path | None:
    """"/…/foo-worktrees/bar/web" のようなパスを "/…/foo" に写像する。"""
    for part in path.parts:
        if part.endswith("-worktrees") and len(part) > len("-worktrees"):
            idx = path.parts.index(part)
            main = Path(*path.parts[:idx]) / part[: -len("-worktrees")]
            if main.is_dir():
                return git_main_worktree(main) or main
    return None


def collect_live() -> list[Live]:
    """docker と ss を突き合わせて 1 本のリストにする。

    docker が publish したポートは ss 側では root 所有の docker-proxy として
    見えるので、docker で説明が付いたポートは ss 側の unattributed を捨てる。
    """
    docker = docker_live()
    explained = {d.port for d in docker}
    merged = list(docker)
    for live in ss_live():
        if live.source == "unattributed" and live.port in explained:
            continue
        if live.source != "unattributed" and live.port in explained:
            # 同じポートを docker とプロセス両方が主張することは通常ない
            continue
        merged.append(live)
    merged.sort(key=lambda x: (x.port, x.bind))
    return fold_dual_stack(merged)


def fold_dual_stack(entries: list[Live]) -> list[Live]:
    """同じポート・同じ中身が IPv4/IPv6 で 2 行に出るのを 1 行に畳む。

    docker は 0.0.0.0 と :: の両方を publish するため、畳まないと一覧が
    倍の長さになって読めなくなる。bind は "0.0.0.0+::" のように併記する。
    """
    grouped: dict[tuple[int, str | None, str, str], list[Live]] = {}
    order: list[tuple[int, str | None, str, str]] = []
    for e in entries:
        key = (e.port, e.project, e.source, e.detail)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(e)

    out: list[Live] = []
    for key in order:
        group = grouped[key]
        head = group[0]
        binds = sorted({g.bind for g in group})
        if len(binds) > 1:
            head = Live(
                port=head.port, bind="+".join(binds), source=head.source,
                project=head.project, repo=head.repo, detail=head.detail,
            )
        out.append(head)
    return out


# --------------------------------------------------------------------------
# 宣言スキャン
# --------------------------------------------------------------------------


def load_env(repo: Path) -> dict[str, str]:
    """repo 直下の .env を読む (compose の ${VAR} 解決用)。"""
    env: dict[str, str] = {}
    for name in (".env", ".env.local"):
        f = repo / name
        if not f.is_file():
            continue
        try:
            for line in f.read_text(errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            continue
    return env


def _mask_specials(spec: str) -> tuple[str, list[tuple[str, str | None]], list[str]]:
    """':' を含む部分 (${VAR:-default} と [IPv6]) をプレースホルダへ退避する。

    素朴に ':' で split すると
      - "${BIND:-127.0.0.1}:${DB_PORT:-55433}:5432" → 変数の中のコロンで割れる
      - "[::1]:5173:5173"                          → IPv6 表記が 4 つ以上に割れる
    のどちらも壊れる。退避してから split し、必要な区画だけ戻す。
    """
    slots: list[tuple[str, str | None]] = []
    brackets: list[str] = []

    def mask_var(m: re.Match) -> str:
        slots.append((m.group(1), m.group(2)))
        return f"\x00{len(slots) - 1}\x00"

    masked = VAR_DEFAULT_RE.sub(mask_var, spec)

    def mask_bracket(m: re.Match) -> str:
        brackets.append(m.group(0))
        return f"\x01{len(brackets) - 1}\x01"

    masked = re.sub(r"\[[^\]]*\]", mask_bracket, masked)
    return masked, slots, brackets


def _unmask_port(segment: str, slots: list[tuple[str, str | None]],
                 env: dict[str, str]) -> tuple[int | None, str | None]:
    """退避した区画を戻してポート番号と変数名を得る。"""
    segment = segment.strip()
    slot_ref = re.fullmatch(r"\x00(\d+)\x00", segment)
    var_name: str | None = None
    if slot_ref:
        name, default = slots[int(slot_ref.group(1))]
        var_name = name
        value = env.get(name) or (default or "")
    else:
        value = segment
    value = value.strip().split("-")[0]  # "8000-8010" は先頭だけ見る
    if not PORT_NUM_RE.match(value):
        return None, var_name
    return int(value), var_name


def scalar_port(raw: str, env: dict[str, str]) -> tuple[int | None, str | None]:
    """compose long syntax の `published:` のように、単体で書かれたホストポート。

    short syntax の単体値 ("6006") は「コンテナ側だけの指定 = ホストはランダム」
    だが、long syntax の published は明示的なホストポートなので意味が逆になる。
    """
    masked, slots, _ = _mask_specials(str(raw).strip().strip('"').strip("'"))
    return _unmask_port(masked, slots, env)


def host_port_and_var(raw: str, env: dict[str, str]) -> tuple[int | None, str | None]:
    """compose short syntax の ports エントリから (ホスト側ポート, 変数名) を取る。

    "127.0.0.1:55433:5432"                     → (55433, None)
    "${BIND:-127.0.0.1}:${DB_PORT:-55433}:5432" → (55433, "DB_PORT")
    "[::1]:5173:5173"                          → (5173, None)
    "6006"                                     → (None, None)
        単体指定はホスト側がランダム割当なので「確保」ではない
    """
    spec = str(raw).strip().strip('"').strip("'")
    if not spec:
        return None, None

    masked, slots, _ = _mask_specials(spec)
    parts = masked.split(":")
    if len(parts) == 3:
        segment = parts[1]
    elif len(parts) == 2:
        segment = parts[0]
    else:
        return None, None
    return _unmask_port(segment, slots, env)


def scan_compose(path: Path, repo: Path, env: dict[str, str]) -> list[Declared]:
    try:
        import yaml
        data = yaml.safe_load(path.read_text(errors="replace"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []

    found: list[Declared] = []
    for svc_name, svc in (data.get("services") or {}).items():
        if not isinstance(svc, dict):
            continue
        for entry in svc.get("ports") or []:
            if isinstance(entry, dict):  # long syntax: published が明示的なホストポート
                published = entry.get("published")
                raw = str(published) if published is not None else ""
                if not raw:
                    continue
                port, var = scalar_port(raw, env)
            else:  # short syntax: "host:container" 形式から host 側を取る
                raw = str(entry)
                if not raw:
                    continue
                port, var = host_port_and_var(raw, env)
            if port is None:
                continue
            found.append(Declared(
                port=port,
                project=repo.name,
                repo=repo,
                origin=f"{path.relative_to(repo)} ({svc_name})",
                var=var,
            ))
    return found


VITE_PORT_RE = re.compile(r"\bport\s*:\s*(\d{2,5})")
CLI_PORT_RE = re.compile(r"--port[= ](\d{2,5})")
ENV_PORT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*PORT[A-Za-z0-9_]*)\s*=\s*(\d{2,5})\s*$")


def scan_text_file(path: Path, repo: Path) -> list[Declared]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []

    found: list[Declared] = []
    rel = path.relative_to(repo)
    name = path.name

    if name.startswith(".env"):
        for i, line in enumerate(text.splitlines(), 1):
            m = ENV_PORT_RE.match(line.strip())
            if m:
                found.append(Declared(
                    port=int(m.group(2)), project=repo.name, repo=repo,
                    origin=f"{rel}:{i}", var=m.group(1), kind="hint",
                ))
        return found

    patterns = [CLI_PORT_RE] if name == "package.json" else [VITE_PORT_RE, CLI_PORT_RE]
    for i, line in enumerate(text.splitlines(), 1):
        for pat in patterns:
            for m in pat.finditer(line):
                port = int(m.group(1))
                if port < 1024:
                    continue  # コンテナ内部の 80/443 等は宣言として扱わない
                found.append(Declared(
                    port=port, project=repo.name, repo=repo, origin=f"{rel}:{i}",
                ))
    return found


def scan_declared(target_repo: Path | None = None) -> list[Declared]:
    """~/repos 全体 (または指定 repo) の宣言ポートを集める。"""
    root = target_repo or REPOS_ROOT
    if not root.exists():
        SOURCE_ISSUES.append(f"{root} が無いため、設定ファイルからの宣言は調べていません")
        return []

    files = list_candidate_files(root)
    by_repo: dict[Path, list[Path]] = {}
    for f in files:
        repo = git_main_worktree(f.parent)
        if repo is None:
            continue
        by_repo.setdefault(repo, []).append(f)

    declared: list[Declared] = []
    for repo, paths in by_repo.items():
        env = load_env(repo)
        for p in paths:
            try:
                p.relative_to(repo)
            except ValueError:
                continue  # worktree 内のファイルはメイン側 repo からの相対にできない
            if p.name.startswith("compose") or p.name.startswith("docker-compose"):
                declared.extend(scan_compose(p, repo, env))
            else:
                declared.extend(scan_text_file(p, repo))
    return declared


def list_candidate_files(root: Path) -> list[Path]:
    """rg --files で候補ファイルを列挙する (無ければ os.walk に落とす)。"""
    if shutil.which("rg"):
        cmd = ["rg", "--files", "--hidden", "--no-messages"]
        for g in SCAN_GLOBS:
            cmd += ["-g", g]
        for g in SCAN_EXCLUDES:
            cmd += ["-g", g]
        cmd.append(str(root))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode in (0, 1):
                return [Path(line) for line in proc.stdout.splitlines() if line]
        except (OSError, subprocess.SubprocessError):
            pass

    names = ("compose", "docker-compose", "vite.config", "package.json", ".env")
    skip = {"node_modules", ".venv", "venv", "dist", "build", ".next", "target", "vendor"}
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if any(fn.startswith(n) for n in names):
                out.append(Path(dirpath) / fn)
    return out


# --------------------------------------------------------------------------
# 台帳
# --------------------------------------------------------------------------


def load_registry() -> Registry:
    reg = Registry(path=REGISTRY_PATH)
    if not REGISTRY_PATH.is_file():
        return reg
    try:
        import yaml
        data = yaml.safe_load(REGISTRY_PATH.read_text(errors="replace")) or {}
    except Exception as exc:
        print(f"WARN: 台帳を読めません ({exc})", file=sys.stderr)
        return reg
    reg.exists = True
    projects = data.get("projects")
    if isinstance(projects, dict):
        for name, entry in projects.items():
            if entry is None:
                reg.projects[str(name)] = {}
            elif isinstance(entry, dict):
                reg.projects[str(name)] = entry
            else:
                SOURCE_ISSUES.append(f"台帳の {name} はマッピングで書いてください (無視しました)")
    elif projects is not None:
        SOURCE_ISSUES.append("台帳の projects はマッピングで書いてください (無視しました)")
    return reg


REGISTRY_TEMPLATE = """# ポート予約台帳 (agent-rules /ports)
#
# ここは案件名を含むため agent-rules (public repo) には置かない。
# 別マシンへ持っていくときは private な dotfiles 等で同期する。
#
# range は [開始, 終了] で両端を含む。案件ごとに帯を宣言しておくと
# `/ports check` が「帯の重複」「帯からの逸脱」「未宣言の占有」を検出する。
version: 1
projects:
  # example-app:
  #   repo: ~/repos/github.com/example-org/example-app
  #   range: [13000, 13099]
  #   note: "13000=frontend 13001=admin 13100=api"
"""


def cmd_registry_init() -> int:
    if REGISTRY_PATH.exists():
        print(f"既にあります: {REGISTRY_PATH}")
        return 0
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(REGISTRY_TEMPLATE)
    print(f"作成しました: {REGISTRY_PATH}")
    return 0


# --------------------------------------------------------------------------
# 出力
# --------------------------------------------------------------------------


def render_table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))
    lines = ["  ".join(pad(h, widths[i]) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(pad(c, widths[i]) for i, c in enumerate(row)))
    return "\n".join(lines)


def display_width(s: str) -> int:
    """全角を 2 幅として数える (日本語混在でも列がズレないように)。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - display_width(s))


def print_source_issues() -> None:
    """情報源の欠落を必ず表示する。

    docker や ss が使えないと live が 0 件になり、そのまま出すと
    「衝突なし」に見えてしまう。検知できなかったことを黙らせない。
    """
    for issue in dict.fromkeys(SOURCE_ISSUES):
        print(f"WARN:  {issue}", file=sys.stderr)


def cmd_list(args) -> int:
    all_live = collect_live()
    # 既定は案件が付いたものだけ。システムサービスや他ユーザのポートまで
    # 出すと、肝心の「自分の案件がどこにいるか」が埋もれる
    live = all_live if args.all else [x for x in all_live if x.project]
    hidden = len(all_live) - len(live)

    rows = []
    for x in live:
        rows.append([
            str(x.port),
            x.bind,
            x.project or "-",
            {"docker": "docker", "process": "proc", "unattributed": "?"}[x.source],
            x.detail or ("root 所有のため不明 (sudo ss -tlnp で確認可)" if x.source == "unattributed" else ""),
        ])

    if args.json:
        print(json.dumps([{
            "port": x.port, "bind": x.bind, "project": x.project,
            "repo": str(x.repo) if x.repo else None,
            "source": x.source, "detail": x.detail,
        } for x in live], ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print("表示できるポートがありません")
    else:
        print(render_table(rows, ["PORT", "BIND", "案件", "種別", "詳細"]))
    print(f"\n{len(live)} 件表示 / 全 {len(all_live)} 件 LISTEN")
    print_source_issues()
    if hidden:
        print(f"案件を特定できなかった {hidden} 件は非表示 (--all で表示)")
    if any("~" in (x.project or "") for x in live):
        print("~ 印はコンテナ名からの推測 (compose ラベルが無い docker run 由来)")
    return 0


def cmd_project(args) -> int:
    key = args.name.lower()
    live = [x for x in collect_live() if x.project and key in x.project.lower()]
    declared = [d for d in scan_declared() if key in d.project.lower()]

    if not live and not declared:
        print(f"'{args.name}' に一致するポートは live にも宣言にも見つかりません")
        print_source_issues()
        return 1

    if live:
        print("■ いま LISTEN しているもの")
        print(render_table(
            [[str(x.port), x.bind, x.project or "-", x.detail] for x in live],
            ["PORT", "BIND", "案件", "詳細"],
        ))
    else:
        print("■ いま LISTEN しているもの: なし (停止中)")

    if declared:
        print("\n■ 設定に書かれているもの")
        seen: set[tuple[int, str]] = set()
        rows = []
        for d in sorted(declared, key=lambda d: d.port):
            k = (d.port, d.origin)
            if k in seen:
                continue
            seen.add(k)
            rows.append([str(d.port), d.project, d.origin, d.var or "-"])
        print(render_table(rows, ["PORT", "案件", "出所", "環境変数"]))
    return 0


def used_ports(live: list[Live], declared: list[Declared], reg: Registry) -> set[int]:
    used = {x.port for x in live} | {d.port for d in declared}
    for name in reg.projects:
        rng = reg.range_of(name)  # 不正値の検証を一箇所に寄せる
        if rng:
            used |= set(range(rng[0], rng[1] + 1))
    return used


def cmd_free(args) -> int:
    live, declared, reg = collect_live(), scan_declared(), load_registry()
    used = used_ports(live, declared, reg)

    lo, hi = args.range
    if args.block:
        size = args.block
        start = lo
        while start + size - 1 <= hi:
            if not any(p in used for p in range(start, start + size)):
                print(f"空き帯: {start}-{start + size - 1} ({size} ポート)")
                print(f"  台帳に登録するには {reg.path} の projects に range: [{start}, {start + size - 1}] を追加")
                return 0
            start += args.align
        print(f"{lo}-{hi} に {size} 連続の空き帯がありません", file=sys.stderr)
        return 1

    found = [p for p in range(lo, hi + 1) if p not in used][: args.count]
    if not found:
        print(f"{lo}-{hi} に空きがありません", file=sys.stderr)
        return 1
    print("空きポート: " + " ".join(str(p) for p in found))
    return 0


def cmd_check(args) -> int:
    """「いま何が起動できないか」を案件単位で答える。

    素朴に「宣言が重なっている」を全部 ERROR にすると 3000/5432/6379 で
    数十件出て読めなくなる。実際に手が止まるのは
    「起動しようとした案件が、既に埋まっているポートを要求する」ときだけなので、
    案件ごとに 1 行へ畳んで出す。案件名を指定すればその案件だけ詳細に見る。
    """
    live, declared, reg = collect_live(), scan_declared(), load_registry()
    binds = [d for d in declared if d.kind == "bind"]

    live_by_port: dict[int, list[Live]] = {}
    for x in live:
        live_by_port.setdefault(x.port, []).append(x)

    def blockers_for(d: Declared) -> set[str]:
        holders = live_by_port.get(d.port) or []
        return {
            strip_marker(h.project) for h in holders
            if h.project and strip_marker(h.project) != d.project
        }

    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    # 1. 台帳の帯どうしの重複 (台帳だけで決まる決定論的な誤り)
    ranges = [(name, r) for name in reg.projects if (r := reg.range_of(name))]
    for i, (n1, (a1, b1)) in enumerate(ranges):
        for n2, (a2, b2) in ranges[i + 1:]:
            if a1 <= b2 and a2 <= b1:
                errors.append(f"台帳の帯が重複: {n1} [{a1}-{b1}] と {n2} [{a2}-{b2}]")

    # 2. 起動を妨げる衝突を案件ごとに集約
    blocked: dict[str, list[tuple[int, set[str], str]]] = {}
    for d in binds:
        others = blockers_for(d)
        if others:
            blocked.setdefault(d.project, []).append((d.port, others, d.origin))

    if args.project:
        key = args.project.lower()
        target = {k: v for k, v in blocked.items() if key in k.lower()}
        declared_for = [d for d in binds if key in d.project.lower()]
        if not declared_for:
            print(f"'{args.project}' のバインド宣言が見つかりません")
            print_source_issues()
            return 1
        if not target:
            # ここで早期 return すると、情報源が欠けていても OK / exit 0 になる。
            # 「調べられなかった」を「問題なし」と混同しないよう共通の末尾へ落とす
            if SOURCE_ISSUES:
                print(f"{args.project} の要求ポートに衝突は見つかりませんでしたが、"
                      f"情報源が欠けているため断定できません")
            else:
                print(f"OK: {args.project} が要求するポートは空いています "
                      f"({len(declared_for)} 件の宣言を確認)")
            print_source_issues()
            return 1 if SOURCE_ISSUES else 0
        for proj, items in sorted(target.items()):
            for port, others, origin in sorted(items):
                errors.append(
                    f"{proj} は {port} を要求するが {', '.join(sorted(others))} が使用中 ({origin})"
                )
    elif blocked:
        for proj, items in sorted(blocked.items()):
            ports = sorted({port for port, _, _ in items})
            holders = sorted({o for _, others, _ in items for o in others})
            warnings.append(
                f"{proj} はいま起動できない — {', '.join(str(p) for p in ports)} を "
                f"{', '.join(holders)} が使用中"
            )

    # 3. 台帳がある場合の帯チェック (案件ごとに 1 行へ畳む)
    unregistered: dict[str, list[int]] = {}
    out_of_range: dict[str, tuple[tuple[int, int], list[int]]] = {}
    for x in live:
        proj = strip_marker(x.project or "")
        if not proj:
            continue
        rng = reg.range_of(proj)
        if rng is None:
            if reg.exists:
                unregistered.setdefault(proj, []).append(x.port)
            continue
        if not (rng[0] <= x.port <= rng[1]):
            entry = out_of_range.setdefault(proj, (rng, []))
            entry[1].append(x.port)

    for proj, ports in sorted(unregistered.items()):
        listed = ", ".join(str(p) for p in sorted(set(ports)))
        warnings.append(f"{proj} は台帳に未登録 ({listed} を使用中)")
    for proj, (rng, ports) in sorted(out_of_range.items()):
        listed = ", ".join(str(p) for p in sorted(set(ports)))
        warnings.append(f"{proj} が帯 [{rng[0]}-{rng[1]}] の外で {listed} を使用中")

    if not reg.exists:
        infos.append(
            f"台帳がありません ({reg.path})。`--registry-init` で作ると帯の検査が有効になります"
        )

    for e in errors:
        print(f"ERROR: {e}")
    for w in sorted(set(warnings)):
        print(f"WARN:  {w}")
    for i in infos:
        print(f"INFO:  {i}")
    if not errors and not warnings:
        if SOURCE_ISSUES:
            print("判定できませんでした (下の WARN のとおり情報源が欠けています)")
        else:
            print("OK: いま起動を妨げる衝突はありません")
    print_source_issues()

    # fail-close: ERROR、または情報源が欠けて判定しきれない場合は非 0
    return 1 if (errors or SOURCE_ISSUES) else 0


def strip_marker(project: str) -> str:
    """表示用の推測マーカー " ~" を落として素の案件名にする。"""
    return project[:-2] if project.endswith(" ~") else project


# --------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="ポート利用状況の棚卸し")
    sub = p.add_subparsers(dest="cmd")

    lp = sub.add_parser("list", help="いま LISTEN しているポートを案件名付きで一覧")
    lp.add_argument("--all", action="store_true", help="案件不明のもの (システム等) も表示")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_list)

    pp = sub.add_parser("project", help="案件名でポートを引く (停止中でも設定から引く)")
    pp.add_argument("name")
    pp.set_defaults(func=cmd_project)

    fp = sub.add_parser("free", help="空きポート / 空き帯を提案")
    fp.add_argument("--count", type=int, default=5)
    fp.add_argument("--block", type=int, help="この個数の連続した空き帯を探す")
    fp.add_argument("--align", type=int, default=100, help="帯探索の刻み (既定 100)")
    fp.add_argument("--range", type=int, nargs=2, default=[10000, 65000], metavar=("LO", "HI"))
    fp.set_defaults(func=cmd_free)

    cp = sub.add_parser("check", help="いま起動できない案件を検出 (案件名を渡すとその案件を詳細に)")
    cp.add_argument("project", nargs="?", help="この案件がいま起動できるかだけを見る")
    cp.set_defaults(func=cmd_check)

    p.add_argument("--registry-init", action="store_true", help="台帳の雛形を作る")
    args = p.parse_args()

    if args.registry_init:
        return cmd_registry_init()
    if not getattr(args, "func", None):
        args = p.parse_args(["list"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
