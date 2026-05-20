#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyvisa>=1.13", "pyvisa-py>=0.7", "psutil>=5.9"]
# ///
"""RIGOL DHO804 data extractor.

Subcommands:
  info        Print *IDN? and last error.
  screenshot  Save current screen as PNG.
  waveform    Dump channel waveform to CSV (time_s, volt_v).
  measure     Read measurement items (VPP, FREQ, ...).
  setup       Save current scope setup (text summary or binary block).
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import pyvisa


CONFIG_PATH = Path.home() / ".config" / "rigol-dho804.toml"

SETUP_QUERIES_GLOBAL = [
    ":TIMebase:MAIN:SCALe?",
    ":TIMebase:MAIN:OFFSet?",
    ":ACQuire:TYPE?",
    ":ACQuire:MDEPth?",
    ":ACQuire:SRATe?",
    ":TRIGger:MODE?",
    ":TRIGger:SWEep?",
    ":TRIGger:EDGE:SOURce?",
    ":TRIGger:EDGE:SLOPe?",
    ":TRIGger:EDGE:LEVel?",
]

SETUP_QUERIES_CHANNEL = [
    ":CHANnel{n}:DISPlay?",
    ":CHANnel{n}:COUPling?",
    ":CHANnel{n}:SCALe?",
    ":CHANnel{n}:OFFSet?",
    ":CHANnel{n}:PROBe?",
    ":CHANnel{n}:BWLimit?",
    ":CHANnel{n}:INVert?",
    ":CHANnel{n}:UNITs?",
]


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    return {}


def resolve_host(args_host: str | None, cfg: dict) -> str:
    if args_host:
        return args_host
    env_host = os.environ.get("RIGOL_DHO804_HOST")
    if env_host:
        return env_host
    cfg_host = cfg.get("host")
    if cfg_host:
        return cfg_host
    sys.exit(
        "error: DHO804 host not specified. Set one of:\n"
        "  --host <ip>\n"
        "  env RIGOL_DHO804_HOST=<ip>\n"
        f'  {CONFIG_PATH} with `host = "<ip>"`'
    )


def open_inst(host: str, timeout_ms: int):
    rm = pyvisa.ResourceManager("@py")
    inst = rm.open_resource(f"TCPIP::{host}::INSTR")
    inst.timeout = timeout_ms
    inst.chunk_size = 1024 * 1024
    return inst


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_binary_block(data: bytes) -> bytes:
    """Strip IEEE 488.2 definite-length binary block header (#NXXXX...)."""
    if not data.startswith(b"#"):
        raise ValueError(f"not a binary block: {data[:16]!r}")
    n = int(data[1:2])
    length = int(data[2 : 2 + n])
    start = 2 + n
    payload = data[start : start + length]
    if len(payload) != length:
        raise ValueError(f"truncated payload: got {len(payload)} expected {length}")
    return payload


def cmd_info(inst, args) -> None:
    print(inst.query("*IDN?").strip())
    try:
        print(f"last error: {inst.query(':SYSTem:ERRor?').strip()}")
    except Exception as e:
        print(f"last error: (query failed: {e})")


def cmd_screenshot(inst, args) -> None:
    inst.timeout = max(inst.timeout, 30000)
    inst.write(":DISPlay:DATA? PNG")
    payload = parse_binary_block(inst.read_raw())
    out = Path(args.output or f"dho804_screen_{ts()}.png")
    out.write_bytes(payload)
    print(f"saved screenshot: {out} ({len(payload)} bytes)")


def cmd_waveform(inst, args) -> None:
    channel = args.channel
    src = f"CHANnel{channel}"
    mode = args.mode.upper()
    fmt = args.format.upper()

    if mode == "RAW":
        inst.write(":STOP")

    inst.write(f":WAVeform:SOURce {src}")
    inst.write(f":WAVeform:MODE {mode}")
    inst.write(f":WAVeform:FORMat {fmt}")

    pre = inst.query(":WAVeform:PREamble?").strip().split(",")
    total_points = int(pre[2])
    xinc = float(pre[4])
    xorig = float(pre[5])
    xref = float(pre[6])
    yinc = float(pre[7])
    yorig = float(pre[8])
    yref = float(pre[9])

    points = min(total_points, args.points) if args.points else total_points
    out = Path(args.output or f"dho804_wfm_ch{channel}_{ts()}.csv")
    written = 0
    with out.open("w") as f:
        f.write("time_s,volt_v\n")
        if fmt == "ASCII":
            inst.write(":WAVeform:STARt 1")
            inst.write(f":WAVeform:STOP {points}")
            raw = inst.query(":WAVeform:DATA?").strip()
            if raw.startswith("#"):
                n = int(raw[1])
                raw = raw[2 + n :]
            for token in raw.rstrip(",\n\r ").split(","):
                if not token:
                    continue
                v = float(token)
                t = (written - xref) * xinc + xorig
                f.write(f"{t:.9e},{v:.6e}\n")
                written += 1
        else:
            chunk = 250_000
            datatype = "B" if fmt == "BYTE" else "h"
            for start_pt in range(1, points + 1, chunk):
                end_pt = min(start_pt + chunk - 1, points)
                inst.write(f":WAVeform:STARt {start_pt}")
                inst.write(f":WAVeform:STOP {end_pt}")
                raw_vals = inst.query_binary_values(
                    ":WAVeform:DATA?",
                    datatype=datatype,
                    is_big_endian=False,
                    container=list,
                )
                for r in raw_vals:
                    v = (r - yref - yorig) * yinc
                    t = (written - xref) * xinc + xorig
                    f.write(f"{t:.9e},{v:.6e}\n")
                    written += 1
    print(f"saved waveform: {out} ({written} points, dt={xinc:.3e}s)")


def cmd_measure(inst, args) -> None:
    src = f"CHANnel{args.channel}"
    for item in args.items:
        item_uc = item.upper()
        try:
            raw = inst.query(f":MEASure:ITEM? {item_uc},{src}").strip()
            val = float(raw)
            if abs(val) > 1e30:
                pretty = "(invalid / not measurable)"
            else:
                pretty = f"{val:.6g}"
            print(f"{item_uc:<10} {src}: {pretty}")
        except Exception as e:
            print(f"{item_uc:<10} {src}: error: {e}")


def cmd_setup(inst, args) -> None:
    if args.binary:
        inst.write(":SYSTem:SETup?")
        payload = parse_binary_block(inst.read_raw())
        out = Path(args.output or f"dho804_setup_{ts()}.stp")
        out.write_bytes(payload)
        print(f"saved binary setup: {out} ({len(payload)} bytes)")
        return

    lines = [f"# DHO804 setup snapshot ({datetime.now().isoformat()})"]
    lines.append(f"# IDN: {inst.query('*IDN?').strip()}")
    lines.append("")
    lines.append("[global]")
    for q in SETUP_QUERIES_GLOBAL:
        try:
            lines.append(f"{q} -> {inst.query(q).strip()}")
        except Exception as e:
            lines.append(f"{q} -> (error: {e})")
    for n in range(1, 5):
        lines.append("")
        lines.append(f"[channel {n}]")
        for tmpl in SETUP_QUERIES_CHANNEL:
            q = tmpl.format(n=n)
            try:
                lines.append(f"{q} -> {inst.query(q).strip()}")
            except Exception as e:
                lines.append(f"{q} -> (error: {e})")
    out = Path(args.output or f"dho804_setup_{ts()}.txt")
    out.write_text("\n".join(lines) + "\n")
    print(f"saved setup summary: {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rigol-dho804", description=__doc__)
    p.add_argument("--host", help="DHO804 IP/hostname (overrides config & env)")
    p.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="VISA timeout ms (overrides config; default 10000)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show *IDN? and last error")

    sc = sub.add_parser("screenshot", help="capture screen as PNG")
    sc.add_argument("-o", "--output", help="output path")

    wf = sub.add_parser("waveform", help="dump waveform to CSV")
    wf.add_argument("-c", "--channel", type=int, default=1)
    wf.add_argument(
        "-m",
        "--mode",
        choices=["normal", "raw", "maximum"],
        default="normal",
        help="normal=screen, raw=full memory (stops scope), maximum=auto",
    )
    wf.add_argument(
        "-f",
        "--format",
        choices=["ascii", "byte", "word"],
        default="byte",
        help="transport format (output is always CSV in volts)",
    )
    wf.add_argument("-n", "--points", type=int, help="cap point count")
    wf.add_argument("-o", "--output", help="output CSV path")

    me = sub.add_parser("measure", help="read measurement items")
    me.add_argument(
        "items",
        nargs="+",
        help="e.g. VPP FREQ PERiod VRMS VMAX VMIN VAVG RTIMe FTIMe PWIDth NWIDth",
    )
    me.add_argument("-c", "--channel", type=int, default=1)

    st = sub.add_parser("setup", help="save current scope setup")
    st.add_argument(
        "--binary",
        action="store_true",
        help="save opaque binary block (.stp) instead of text summary",
    )
    st.add_argument("-o", "--output", help="output path")

    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg = load_config()
    host = resolve_host(args.host, cfg)
    timeout_ms = args.timeout if args.timeout is not None else int(cfg.get("timeout", 10000))
    inst = open_inst(host, timeout_ms=timeout_ms)
    try:
        {
            "info": cmd_info,
            "screenshot": cmd_screenshot,
            "waveform": cmd_waveform,
            "measure": cmd_measure,
            "setup": cmd_setup,
        }[args.cmd](inst, args)
    finally:
        try:
            inst.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
