#!/usr/bin/env python3
"""webcam-jetson client — talk to the on-Jetson HTTP API + SSH for install/control.

Subcommands:
  snapshot     pull one JPEG frame
  record       record N seconds, download the file
  stream-url   print live-view URL + copy-paste command (mjpeg | rtsp | hls)
  install      rsync server/ to Jetson and run install.sh
  status       systemctl status + /healthz
  restart      sudo systemctl restart on Jetson
  logs         journalctl -u on Jetson
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27", "tomli; python_version<'3.11'"]
# ///

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


CONFIG_PATH = Path.home() / ".config" / "webcam-jetson.toml"
DEFAULTS = {
    "http_host": "jetson-nano",
    "http_port": 8080,
    "rtsp_port": 8554,
    "hls_port": 8888,
    "ssh_host": "elmo@jetson-nano",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    return {}


def resolve(args: argparse.Namespace, attr: str, env_name: str, default):
    val = getattr(args, attr, None)
    if val is not None:
        return val
    if env_name in os.environ:
        return os.environ[env_name]
    cfg_key = attr.replace("_", "_")
    cfg = load_config()
    if cfg_key in cfg:
        return cfg[cfg_key]
    return default


def base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


# ---------- subcommands ----------

def cmd_snapshot(args: argparse.Namespace) -> int:
    url = f"{base_url(args.host, args.port)}/snapshot.jpg"
    params: dict[str, str] = {}
    if args.width:
        params["w"] = str(args.width)
    if args.height:
        params["h"] = str(args.height)
    out = Path(args.output) if args.output else Path(
        f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
    )
    try:
        r = httpx.get(url, params=params, timeout=15.0)
    except httpx.HTTPError as e:
        print(f"error: GET {url} failed: {e}", file=sys.stderr)
        return 2
    if r.status_code != 200:
        print(f"error: {r.status_code} {r.text[:300]}", file=sys.stderr)
        return 2
    out.write_bytes(r.content)
    print(f"saved: {out} ({len(r.content):,} bytes)")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    api = base_url(args.host, args.port)
    print(f"requesting {args.duration}s recording ({args.format}) ...")
    try:
        r = httpx.post(
            f"{api}/record",
            params={"duration": args.duration, "format": args.format},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        print(f"error: POST /record failed: {e}", file=sys.stderr)
        return 2
    if r.status_code != 202:
        print(f"error: {r.status_code} {r.text[:300]}", file=sys.stderr)
        return 2
    job = r.json()
    rid = job["id"]
    fname = job["filename"]
    print(f"recording id={rid} filename={fname}")

    deadline = time.time() + args.duration + 30
    poll_interval = max(1.0, args.duration / 6)
    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            h = httpx.get(f"{api}/healthz", timeout=5.0).json()
        except httpx.HTTPError:
            continue
        if rid not in h.get("active_recordings", []):
            break
    else:
        print("warning: recording still in progress after deadline", file=sys.stderr)

    out = Path(args.output) if args.output else Path(fname)
    print(f"downloading -> {out}")
    try:
        with httpx.stream("GET", f"{api}/recordings/{fname}", timeout=120.0) as resp:
            if resp.status_code != 200:
                resp.read()
                print(f"error: download {resp.status_code} {resp.text[:300]}", file=sys.stderr)
                return 2
            with out.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    except httpx.HTTPError as e:
        print(f"error: download failed: {e}", file=sys.stderr)
        return 2
    print(f"saved: {out} ({out.stat().st_size:,} bytes)")
    return 0


def cmd_stream_url(args: argparse.Namespace) -> int:
    host = args.host
    proto = args.protocol
    if proto == "mjpeg":
        url = f"{base_url(host, args.port)}/stream.mjpg"
        print(f"URL: {url}\n")
        print("Open in browser, or:")
        print(f"  mpv {url}")
        print(f"  ffplay {url}")
    elif proto == "rtsp":
        rtsp_port = args.rtsp_port or DEFAULTS["rtsp_port"]
        url = f"rtsp://{host}:{rtsp_port}/cam"
        print(f"URL: {url}\n")
        print("Recommended (TCP transport — robust over Tailscale):")
        print(f"  vlc {url}")
        print(f"  ffplay -rtsp_transport tcp {url}")
        print(f"  mpv --rtsp-transport=tcp {url}")
    elif proto == "hls":
        hls_port = args.hls_port or DEFAULTS["hls_port"]
        url = f"http://{host}:{hls_port}/cam/index.m3u8"
        print(f"URL: {url}\n")
        print("  vlc " + url)
        print("  # Or open URL directly in Safari (native HLS)")
    else:
        print(f"unknown protocol: {proto}", file=sys.stderr)
        return 2
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    server_src = Path(__file__).resolve().parent.parent / "server"
    if not server_src.is_dir():
        print(f"error: server source not found at {server_src}", file=sys.stderr)
        return 2
    print(f"==> rsync {server_src}/ -> {args.ssh_host}:~/webcam-jetson/")
    rc = subprocess.call([
        "rsync", "-az", "--delete",
        f"{server_src}/", f"{args.ssh_host}:~/webcam-jetson/",
    ])
    if rc != 0:
        return rc
    print(f"==> running install.sh on {args.ssh_host}")
    return subprocess.call(["ssh", args.ssh_host, "bash ~/webcam-jetson/install.sh"])


def cmd_status(args: argparse.Namespace) -> int:
    print(f"==> systemctl status on {args.ssh_host}:")
    subprocess.call([
        "ssh", args.ssh_host,
        "systemctl --no-pager --lines=5 status webcam-mediamtx webcam-server",
    ])
    print(f"\n==> {base_url(args.host, args.port)}/healthz:")
    try:
        h = httpx.get(f"{base_url(args.host, args.port)}/healthz", timeout=5.0).json()
        print(json.dumps(h, indent=2, ensure_ascii=False))
    except httpx.HTTPError as e:
        print(f"  failed: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    return subprocess.call([
        "ssh", args.ssh_host,
        "sudo systemctl restart webcam-mediamtx webcam-server && "
        "systemctl --no-pager --lines=0 status webcam-mediamtx webcam-server",
    ])


def cmd_logs(args: argparse.Namespace) -> int:
    follow = "-f" if args.follow else ""
    return subprocess.call([
        "ssh", args.ssh_host,
        f"journalctl --no-pager -n {args.lines} {follow} -u {args.unit}",
    ])


# ---------- argparse ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="webcam_jetson", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def http_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--host", help=f"HTTP host (default: {DEFAULTS['http_host']})")
        sp.add_argument("--port", type=int,
                        help=f"HTTP port (default: {DEFAULTS['http_port']})")

    def ssh_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--ssh-host",
                        help=f"SSH target (default: {DEFAULTS['ssh_host']})")

    sp = sub.add_parser("snapshot", help="pull one JPEG frame")
    http_opts(sp)
    sp.add_argument("-o", "--output")
    sp.add_argument("--width", type=int)
    sp.add_argument("--height", type=int)
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("record", help="record N seconds and download")
    http_opts(sp)
    sp.add_argument("-d", "--duration", type=int, default=10)
    sp.add_argument("-f", "--format", choices=["mkv", "mp4"], default="mkv")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("stream-url", help="print live-view URL + copy-paste command")
    http_opts(sp)
    sp.add_argument("--rtsp-port", type=int, dest="rtsp_port")
    sp.add_argument("--hls-port", type=int, dest="hls_port")
    sp.add_argument("protocol", choices=["mjpeg", "rtsp", "hls"], nargs="?", default="mjpeg")
    sp.set_defaults(func=cmd_stream_url)

    sp = sub.add_parser("install", help="rsync server/ and run install.sh on Jetson")
    ssh_opts(sp)
    sp.set_defaults(func=cmd_install)

    sp = sub.add_parser("status", help="systemctl status + /healthz")
    http_opts(sp)
    ssh_opts(sp)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("restart", help="sudo systemctl restart on Jetson")
    ssh_opts(sp)
    sp.set_defaults(func=cmd_restart)

    sp = sub.add_parser("logs", help="journalctl -u on Jetson")
    ssh_opts(sp)
    sp.add_argument("-n", "--lines", type=int, default=50)
    sp.add_argument("-f", "--follow", action="store_true")
    sp.add_argument("--unit", default="webcam-server",
                    choices=["webcam-server", "webcam-mediamtx"])
    sp.set_defaults(func=cmd_logs)

    return p


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_config()
    if hasattr(args, "host"):
        args.host = args.host or os.getenv("WCAM_HTTP_HOST") or cfg.get("http_host") or DEFAULTS["http_host"]
    if hasattr(args, "port"):
        args.port = args.port or (int(os.getenv("WCAM_HTTP_PORT")) if os.getenv("WCAM_HTTP_PORT") else None) \
                    or cfg.get("http_port") or DEFAULTS["http_port"]
    if hasattr(args, "ssh_host"):
        args.ssh_host = args.ssh_host or os.getenv("WCAM_SSH_HOST") or cfg.get("ssh_host") or DEFAULTS["ssh_host"]
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
