#!/usr/bin/env python3
"""mosh-clean — このホスト上に残存した mosh-server セッションを安全に一覧/終了する。

mosh-server はクライアントのネットワークが切れても終了せず再接続を待ち続けるため、
ノート PC を閉じる・回線が変わる等で「もう誰も使っていない」プロセスが溜まりやすい。
このスクリプトは:

  - list : 全 mosh-server を PID/UDP ポート/接続元 IP/ログイン時刻/idle/中で動いている
           プロセス 付きで一覧し、いま自分が使っているセッション (current) を検出して保護対象に印を付ける。
  - kill : 指定 PID の mosh-server を SIGTERM (必要なら SIGKILL) で終了する。
           安全装置: (1) mosh-server 以外の PID は拒否、(2) current セッションは --force なしでは拒否。

stdlib のみ (外部依存なし)。情報源は /proc, who, ss。Linux 専用。
"""

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import time

PROC = "/proc"


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def _pids():
    return [int(p) for p in os.listdir(PROC) if p.isdigit()]


def _cmdline(pid):
    try:
        with open(f"{PROC}/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _comm(pid):
    """実行ファイル名 (comm)。引数に 'mosh-server' を含むだけの無関係プロセスと区別するため使う。"""
    try:
        with open(f"{PROC}/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def _stat(pid):
    """/proc/<pid>/stat を読み、必要フィールドを返す。comm に空白/括弧があっても安全に分解する。"""
    try:
        with open(f"{PROC}/{pid}/stat") as f:
            data = f.read()
    except OSError:
        return None
    rp = data.rfind(")")
    if rp < 0:
        return None
    rest = data[rp + 2 :].split()
    # rest[0]=state rest[1]=ppid rest[2]=pgrp rest[3]=session rest[4]=tty_nr rest[5]=tpgid
    try:
        return {
            "state": rest[0],
            "ppid": int(rest[1]),
            "pgrp": int(rest[2]),
            "tty_nr": int(rest[4]),
            "tpgid": int(rest[5]),
        }
    except (IndexError, ValueError):
        return None


def _tty_name(tty_nr):
    """tty_nr (dev_t) を pts/N 等の名前に変換する。pts は major 136。"""
    if not tty_nr:
        return None
    major = (tty_nr >> 8) & 0xFFF
    minor = (tty_nr & 0xFF) | ((tty_nr >> 12) & 0xFFF00)
    if major == 136:
        return f"pts/{minor}"
    if major == 4:
        return f"tty{minor}"
    return None


def _tty_of(pid):
    st = _stat(pid)
    return _tty_name(st["tty_nr"]) if st else None


def _ppid_of(pid):
    st = _stat(pid)
    return st["ppid"] if st else None


def _children(pid, all_stats):
    return [p for p, st in all_stats.items() if st and st["ppid"] == pid]


def _ss_ports():
    """pid -> (local_ip, port) を ss から得る。"""
    out = _run(["ss", "-unap"])
    res = {}
    for line in out.splitlines():
        if "mosh-server" not in line:
            continue
        cols = line.split()
        local = None
        for c in cols:
            if ":" in c and re.search(r":\d+$", c):
                local = c
                break
        m = re.search(r"pid=(\d+)", line)
        if local and m:
            ip, _, port = local.rpartition(":")
            res[int(m.group(1))] = (ip, port)
    return res


def _who():
    """mosh PID -> (source_ip, login 'MM-DD HH:MM') を who -u から得る。"""
    out = _run(["who", "-u"])
    res = {}
    for line in out.splitlines():
        if "mosh" not in line:
            continue
        # 例: elmo pts/8 2026-06-27 13:44 . 1633893 (100.86.37.21 via mosh [1633893])
        ipm = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        pidm = re.search(r"\[(\d+)\]", line) or re.search(r"\s(\d{2,})\s", line)
        datem = re.search(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})", line)
        if not pidm:
            continue
        pid = int(pidm.group(1))
        ip = ipm.group(1) if ipm else "?"
        login = f"{datem.group(2)}-{datem.group(3)} {datem.group(4)}" if datem else "?"
        res[pid] = (ip, login)
    return res


def _idle_secs(pts):
    """pts デバイスの atime から idle 秒を計算 (who の idle と同義)。"""
    if not pts:
        return None
    try:
        atime = os.stat(f"/dev/{pts}").st_atime
        return max(0, int(time.time() - atime))
    except OSError:
        return None


def _fmt_idle(secs):
    if secs is None:
        return "?"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"
    return f"{secs // 86400}d{(secs % 86400) // 3600:02d}h"


def _foreground_cmd(pts, all_stats):
    """pts の前景プロセスグループの代表コマンドを返す (何が動いているか)。"""
    if not pts:
        return "?"
    # この pts を制御端末に持つプロセスのうち tpgid を取り、その pgrp に一致する前景プロセスを探す。
    members = [p for p, st in all_stats.items() if st and _tty_name(st["tty_nr"]) == pts]
    if not members:
        return "?"
    tpgid = None
    for p in members:
        t = all_stats[p]["tpgid"]
        if t > 0:
            tpgid = t
            break
    fg = [p for p in members if all_stats[p]["pgrp"] == tpgid] if tpgid else []
    target = min(fg) if fg else min(members)
    cl = _cmdline(target) or "?"
    cl = cl.lstrip("-")  # ログインシェル -bash → bash
    # 長い zellij サーバパス等は短縮
    m = re.search(r"zellij\s+attach\s+(?:--create\s+)?(\S+)", cl)
    if m:
        return f"zellij attach {m.group(1)}"
    return (cl[:48] + "…") if len(cl) > 49 else cl


def find_mosh_servers(all_stats):
    """mosh-server プロセスを列挙して各種メタを付与する。"""
    ss = _ss_ports()
    who = _who()
    servers = []
    for pid, st in all_stats.items():
        # 実行ファイル名で厳密判定 (引数に文字列を含むだけのプロセスや zombie を除外)
        if _comm(pid) != "mosh-server":
            continue
        if st and st.get("state") == "Z":
            continue
        # 子シェルの pts を採用 (mosh-server 自体は端末を持たない)
        child = next(iter(_children(pid, all_stats)), None)
        pts = _tty_of(child) if child else None
        ip, login = who.get(pid, ("?", "?"))
        ss_ip, port = ss.get(pid, (None, "?"))
        idle = _idle_secs(pts)
        servers.append(
            {
                "pid": pid,
                "pts": pts,
                "port": port,
                "source": ip,
                "login": login,
                "idle": idle,
                "running": _foreground_cmd(pts, all_stats),
            }
        )
    servers.sort(key=lambda s: (-(s["idle"] or 0)))  # idle が長い (= 残存疑い) を上に
    return servers


def detect_current(all_stats, servers):
    """いま自分 (このプロセス) が乗っている mosh-server PID を多層検出する。

    1. 直接: 祖先プロセスの制御端末が mosh の pts と一致 (multiplexer なしの場合)。
    2. 間接: 祖先に zellij/tmux サーバがいればセッション名を取り、その attach クライアントの
       制御端末 pts から mosh を逆引き (zellij はサーバが init に reparent されるため必要)。
    検出できなければ None。
    """
    pts_to_mosh = {s["pts"]: s["pid"] for s in servers if s["pts"]}

    # 祖先チェーンを収集
    ancestors = []
    p = os.getpid()
    seen = set()
    while p and p > 1 and p not in seen:
        seen.add(p)
        ancestors.append(p)
        p = _ppid_of(p) or 0

    # 1. 直接 tty 一致
    for a in ancestors:
        t = _tty_of(a)
        if t in pts_to_mosh:
            return pts_to_mosh[t]

    # 2. multiplexer 経由 (zellij)
    session_name = None
    for a in ancestors:
        cl = _cmdline(a)
        m = re.search(r"zellij\s+--server\s+\S+/([^/\s]+)\s*$", cl)
        if m:
            session_name = m.group(1)
            break
    if session_name:
        for pid, st in all_stats.items():
            cl = _cmdline(pid)
            toks = cl.split()
            # session 名は引数トークンとして完全一致で照合 (例: agent-rules を agent-rules-vt に誤一致させない)
            if "zellij" in cl and "attach" in toks and session_name in toks:
                t = _tty_of(pid)
                if t in pts_to_mosh:
                    return pts_to_mosh[t]

    # 2'. multiplexer 経由 (tmux, best-effort)
    in_tmux = any("tmux" in _cmdline(a) for a in ancestors)
    if in_tmux:
        for pid, st in all_stats.items():
            cl = _cmdline(pid)
            if re.search(r"\btmux\b.*\battach", cl) or re.search(r"\btmux\b.*\b-CC?\b", cl):
                t = _tty_of(pid)
                if t in pts_to_mosh:
                    return pts_to_mosh[t]
    return None


def cmd_list(args):
    all_stats = {p: _stat(p) for p in _pids()}
    servers = find_mosh_servers(all_stats)
    current = detect_current(all_stats, servers)

    host = socket.gethostname()
    if not servers:
        print(f"mosh-server セッションなし (host: {host})")
        return 0

    print(f"MOSH SESSIONS  (host: {host})  — {len(servers)} 件")
    if current:
        print(f"current session = PID {current} (保護対象 / --force なしでは kill 不可)")
    else:
        print("current session = 不明 (multiplexer 構成等)。kill する PID が今使っている")
        print("  セッションでないか source/idle で必ず確認すること。")
    print()
    hdr = f"{'PID':>8}  {'PORT':>5}  {'SOURCE':<15}  {'LOGIN':<11}  {'IDLE':>7}  RUNNING"
    print(hdr)
    print("-" * len(hdr))
    for s in servers:
        mark = "  ← CURRENT" if s["pid"] == current else ""
        print(
            f"{s['pid']:>8}  {s['port']:>5}  {s['source']:<15}  {s['login']:<11}  "
            f"{_fmt_idle(s['idle']):>7}  {s['running']}{mark}"
        )
    print()
    print("終了するには: mosh_clean.py kill <PID> [<PID> ...]")
    print("idle が長く中身が素の bash のものは残存の可能性が高い (ただし最終判断は人間)。")
    return 0


def _is_mosh_server(pid):
    return _comm(pid) == "mosh-server"


def _is_zombie(pid):
    st = _stat(pid)
    return bool(st) and st.get("state") == "Z"


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cmd_kill(args):
    all_stats = {p: _stat(p) for p in _pids()}
    servers = find_mosh_servers(all_stats)
    current = detect_current(all_stats, servers)

    rc = 0
    for pid in args.pids:
        if not _alive(pid):
            print(f"PID {pid}: 存在しない (既に終了済み?)")
            continue
        if _is_zombie(pid):
            print(f"PID {pid}: zombie (既に終了し親の reap 待ち)。kill 不要。")
            continue
        if not _is_mosh_server(pid):
            print(f"PID {pid}: mosh-server ではないため拒否 (安全装置)。cmd={_cmdline(pid)[:60]!r}")
            rc = 1
            continue
        if pid == current and not args.force:
            print(f"PID {pid}: いま使っている current セッションのため拒否。本当に消すなら --force。")
            rc = 1
            continue
        if args.dry_run:
            print(f"PID {pid}: [dry-run] SIGTERM を送る予定" + (" (current!)" if pid == current else ""))
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            print(f"PID {pid}: SIGTERM 失敗 ({e})")
            rc = 1
            continue
        # 終了待ち (最大 ~2s)。zombie 化も「終了」とみなす。
        gone = lambda: (not _alive(pid)) or _is_zombie(pid)
        for _ in range(20):
            if gone():
                break
            time.sleep(0.1)
        if not gone():
            try:
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.3)
                print(f"PID {pid}: SIGTERM で落ちず SIGKILL を送信 → " + ("終了" if gone() else "まだ生存 (権限不足の可能性)"))
                if not gone():
                    rc = 1
            except OSError as e:
                print(f"PID {pid}: SIGKILL 失敗 ({e})")
                rc = 1
        else:
            print(f"PID {pid}: 終了 (SIGTERM)")
    return rc


def main():
    ap = argparse.ArgumentParser(prog="mosh_clean.py", description="残存 mosh-server セッションの一覧/終了")
    sub = ap.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="mosh-server セッションを一覧 (既定)")
    p_list.set_defaults(func=cmd_list)

    p_kill = sub.add_parser("kill", help="指定 PID の mosh-server を終了")
    p_kill.add_argument("pids", nargs="+", type=int, help="終了する mosh-server の PID")
    p_kill.add_argument("--force", action="store_true", help="current セッションでも強制終了")
    p_kill.add_argument("--dry-run", action="store_true", help="送信せず予定だけ表示")
    p_kill.set_defaults(func=cmd_kill)

    args = ap.parse_args()
    if not args.cmd:
        args.func = cmd_list
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
