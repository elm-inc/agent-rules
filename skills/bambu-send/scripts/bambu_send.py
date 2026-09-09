#!/usr/bin/env python3
"""Bambu Lab プリンタへ LAN 経由でファイルを送り、印刷を開始する。

**標準ライブラリだけで動く。** paho-mqtt も bambulabs_api も要らない。
呼び出し元 (ai-cad 等) の依存を汚さないため、MQTT 3.1.1 は手で喋る。

経路は 2 本:

- **FTPS (990, implicit TLS)** — ファイルを置く。ユーザ名 `bblp` / パスワードは
  LAN アクセスコード
- **MQTT (8883, TLS)** — `device/<SN>/request` に指示を publish し、
  `device/<SN>/report` で状態を読む

どちらも証明書は自己署名なので検証しない (LAN 内・機器が固定である前提)。

安全の線:

- **アクセスコードを argv に出さない。** 設定ファイルか環境変数からのみ読む
- **`print` は `--yes` が要る。** 印刷はフィラメントを消費する戻せない操作である
- **送る前に中身を検査する。** 3mf に指定プレートの g-code が無ければ**送らない**
  (「書く前に検査して、通らなければ書かない」)
- **常駐しない。** publish して短く見届けたら終了する
- **利用者のファイルを消さない。** 削除系のサブコマンドを持たない
"""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import tomllib
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

CONFIG = Path.home() / ".config" / "agent-rules" / "bambu.toml"

FTPS_PORT = 990
MQTT_PORT = 8883
SSDP_PORT = 2021
SSDP_GROUP = "239.255.255.250"


class Fail(Exception):
    """利用者に見せるエラー。トレースバックは出さない。"""


def pad(label: str, width: int) -> str:
    """全角を 2 桁として揃える (str.ljust は表示幅を見ないので日本語がズレる)。"""
    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in label)
    return label + " " * max(0, width - shown)


# --------------------------------------------------------------------------
# 設定
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Printer:
    name: str
    host: str
    serial: str
    access_code: str
    bed_type: str = "textured_plate"


def load_printer(name: str | None) -> Printer:
    """設定ファイル or 環境変数からプリンタを 1 台選ぶ。

    **アクセスコードは argv からは受け取らない** (ps に出る)。
    """
    env = {k: os.environ.get(k) for k in ("BAMBU_HOST", "BAMBU_SERIAL", "BAMBU_ACCESS_CODE")}
    if all(env.values()):
        return Printer(
            name=name or "env",
            host=env["BAMBU_HOST"],  # type: ignore[arg-type]
            serial=env["BAMBU_SERIAL"],  # type: ignore[arg-type]
            access_code=env["BAMBU_ACCESS_CODE"],  # type: ignore[arg-type]
        )

    if not CONFIG.exists():
        raise Fail(
            f"設定がありません: {CONFIG}\n"
            "  `bambu_send.py init` が雛形を書きます "
            "(アクセスコードはプリンタ画面 → 設定 → ネットワーク)。\n"
            "  環境変数 BAMBU_HOST / BAMBU_SERIAL / BAMBU_ACCESS_CODE でも可"
        )
    data = tomllib.loads(CONFIG.read_text("utf-8"))
    printers = data.get("printer") or {}
    if not printers:
        raise Fail(f"{CONFIG} に [printer.<名前>] がありません")
    if name is None:
        default = data.get("default")
        if default is not None:
            name = str(default)
        elif len(printers) == 1:
            name = next(iter(printers))
        else:
            # **既定に倒さない。** 複数あるなら、どれかを人が選ぶ。
            raise Fail(
                "プリンタが複数あります。--printer で選んでください: "
                + ", ".join(sorted(printers))
            )
    if name not in printers:
        raise Fail(f"プリンタ {name!r} が設定にありません (ある: {', '.join(sorted(printers))})")
    p = printers[name]
    missing = [k for k in ("host", "serial", "access_code") if not p.get(k)]
    if missing:
        raise Fail(f"[printer.{name}] に {', '.join(missing)} がありません")
    return Printer(
        name=name,
        host=str(p["host"]),
        serial=str(p["serial"]),
        access_code=str(p["access_code"]),
        bed_type=str(p.get("bed_type", "textured_plate")),
    )


# --------------------------------------------------------------------------
# SSDP 発見
# --------------------------------------------------------------------------


def discover(seconds: float = 8.0) -> list[dict[str, str]]:
    """LAN の Bambu 機を探す。バインドできなければその旨を返す。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", SSDP_PORT))
    except OSError as e:
        raise Fail(
            f"UDP {SSDP_PORT} を bind できません ({e})。Bambu Studio が起動中かもしれません"
        ) from e
    mreq = struct.pack("4sl", socket.inet_aton(SSDP_GROUP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    probe = (
        b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:2021\r\n"
        b'MAN: "ssdp:discover"\r\nMX: 1\r\n'
        b"ST: urn:bambulab-com:device:3dprinter:1\r\n\r\n"
    )
    for port in (1990, SSDP_PORT):
        try:
            tx.sendto(probe, (SSDP_GROUP, port))
        except OSError:
            pass

    mine = _local_addresses()
    sock.settimeout(1.0)
    found: dict[str, dict[str, str]] = {}
    end = time.time() + seconds
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(8192)
        except TimeoutError:
            continue
        text = data.decode("utf-8", "replace")
        # **自分が投げた M-SEARCH がマルチキャストで返ってくる。** 送信元 IP での
        # 除外は当てにならない (多数の interface を持つホストで漏れた) ので、
        # 「探索要求は自分のもの」という意味で弾く。プリンタの応答は NOTIFY。
        if text.upper().startswith("M-SEARCH"):
            continue
        if addr[0] in mine:
            continue
        if "bambu" not in text.lower():
            continue
        fields: dict[str, str] = {"ip": addr[0]}
        for line in text.splitlines():
            key, _, value = line.partition(":")
            key = key.strip()
            if key in ("USN", "Location"):
                fields[key.lower()] = value.strip()
            elif key.endswith(".bambu.com"):
                fields[key.split(".")[0].removeprefix("Dev").lower()] = value.strip()
        found[addr[0]] = fields
    return list(found.values())


def _local_addresses() -> set[str]:
    out = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.add(info[4][0])
    except OSError:
        pass
    # 既定経路に出ていく側の住所も足す (hostname が引けない環境で効く)
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1。実際には送らない
        out.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------
# FTPS
# --------------------------------------------------------------------------


class ImplicitFTPS(ftplib.FTP_TLS):
    """990 は接続直後から TLS (explicit の AUTH TLS ではない)。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sock: ssl.SSLSocket | None = None

    @property
    def sock(self):  # type: ignore[override]
        return self._sock

    @sock.setter
    def sock(self, value) -> None:
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            # **制御接続の TLS セッションを使い回す。** 再開しないと拒否される。
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session  # type: ignore[union-attr]
            )
        return conn, size

    def storbinary(self, cmd, fp, blocksize=8192, callback=None, rest=None):  # type: ignore[override]
        self.voidcmd("TYPE I")
        conn = self.transfercmd(cmd, rest)
        try:
            while True:
                buf = fp.read(blocksize)
                if not buf:
                    break
                conn.sendall(buf)
                if callback:
                    callback(buf)
            # **TLS の後始末は best-effort。** 綺麗に unwrap すると応答待ちが
            # 早く返る機体がある一方、A1 mini (fw 01.08.01) は close_notify を
            # 返さず読みで固まる (実測: 転送は成功しているのに TimeoutError)。
            # **転送が終わった後の儀式で失敗を報告しない。**
            if isinstance(conn, ssl.SSLSocket):
                conn.settimeout(3.0)
                try:
                    conn.unwrap()
                except (OSError, ssl.SSLError):
                    pass
        finally:
            conn.close()
        return self.voidresp()


def ftps_connect(printer: Printer, timeout: float = 15.0) -> ImplicitFTPS:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # 自己署名
    ftps = ImplicitFTPS(context=ctx)
    try:
        ftps.connect(printer.host, FTPS_PORT, timeout=timeout)
        ftps.login("bblp", printer.access_code)
        ftps.prot_p()
    except ftplib.error_perm as e:
        raise Fail(f"FTPS ログインに失敗しました ({e})。アクセスコードを確認してください") from e
    except OSError as e:
        raise Fail(f"FTPS に繋がりません ({printer.host}:{FTPS_PORT}): {e}") from e
    ftps.set_pasv(True)
    return ftps


# --------------------------------------------------------------------------
# MQTT (3.1.1 を手で喋る)
# --------------------------------------------------------------------------


def _varint(n: int) -> bytes:
    out = b""
    while True:
        byte = n % 128
        n //= 128
        out += bytes([byte | (0x80 if n else 0)])
        if not n:
            return out


def _mqtt_str(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("!H", len(raw)) + raw


class Mqtt:
    """1 回の用事のために繋いで、終わったら閉じる。**常駐しない。**"""

    def __init__(self, printer: Printer, timeout: float = 15.0) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            raw = socket.create_connection((printer.host, MQTT_PORT), timeout=timeout)
        except OSError as e:
            raise Fail(f"MQTT に繋がりません ({printer.host}:{MQTT_PORT}): {e}") from e
        self.sock = ctx.wrap_socket(raw)
        self.serial = printer.serial
        self.buf = b""

        payload = _mqtt_str("bambu-send") + _mqtt_str("bblp") + _mqtt_str(printer.access_code)
        var = _mqtt_str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
        self._send(b"\x10", var + payload)

        head, body = self._packet()
        if head >> 4 != 2:
            raise Fail(f"CONNACK が返りませんでした ({head:#x})")
        rc = body[1]
        if rc != 0:
            reasons = {
                1: "プロトコル版が拒否されました",
                2: "クライアント ID が拒否されました",
                3: "サービスが利用できません",
                4: "ユーザ名/パスワードが違います (アクセスコードを確認してください)",
                5: "認可されていません",
            }
            raise Fail(f"MQTT 認証に失敗しました: {reasons.get(rc, f'rc={rc}')}")
        topic = _mqtt_str(f"device/{self.serial}/report")
        self._send(b"\x82", struct.pack("!H", 1) + topic + b"\x00")

    def _send(self, head: bytes, body: bytes) -> None:
        self.sock.sendall(head + _varint(len(body)) + body)

    def _need(self, n: int) -> None:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise Fail("MQTT 接続が切れました")
            self.buf += chunk

    def _packet(self) -> tuple[int, bytes]:
        self._need(1)
        head = self.buf[0]
        mult, value, i = 1, 0, 1
        while True:
            self._need(i + 1)
            byte = self.buf[i]
            value += (byte & 127) * mult
            mult *= 128
            i += 1
            if not byte & 0x80:
                break
        self._need(i + value)
        body = self.buf[i : i + value]
        self.buf = self.buf[i + value :]
        return head, body

    def publish(self, message: dict) -> None:
        body = _mqtt_str(f"device/{self.serial}/request") + json.dumps(message).encode()
        self._send(b"\x30", body)

    def listen(self, seconds: float):
        """届いた JSON を順に返す。時間切れで止まる。"""
        self.sock.settimeout(1.0)
        end = time.time() + seconds
        while time.time() < end:
            try:
                head, body = self._packet()
            except (TimeoutError, ssl.SSLWantReadError):
                continue
            if head >> 4 != 3:
                continue
            tlen = struct.unpack("!H", body[:2])[0]
            try:
                yield json.loads(body[2 + tlen :])
            except json.JSONDecodeError:
                continue

    def state(self, seconds: float = 10.0) -> dict:
        """状態を 1 回だけ取る (pushall は「吐け」という要求で、機械は動かない)。"""
        self.publish({"pushing": {"sequence_id": "0", "command": "pushall"}})
        merged: dict = {}
        for message in self.listen(seconds):
            part = message.get("print")
            if isinstance(part, dict):
                merged.update(part)
                if "gcode_state" in merged:
                    break
        if not merged:
            raise Fail("状態が返ってきませんでした")
        return merged

    def close(self) -> None:
        try:
            self.sock.sendall(b"\xe0\x00")  # DISCONNECT
        except OSError:
            pass
        self.sock.close()


# --------------------------------------------------------------------------
# 3mf の検査
# --------------------------------------------------------------------------


def inspect_3mf(path: Path, plate: int) -> str:
    """送る前に中身を確かめる。**通らなければ送らない。**"""
    if not path.exists():
        raise Fail(f"ファイルがありません: {path}")
    if path.suffix.lower() != ".3mf":
        raise Fail(
            f"スライス済みの .3mf を渡してください (受け取った: {path.name})。\n"
            "  形状だけの STL/STEP は印刷できません。Bambu Studio でスライスして\n"
            "  「プレートをエクスポート」するか、reference/slicing.md の CLI 手順で作ります"
        )
    member = f"Metadata/plate_{plate}.gcode"
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if member not in names:
                plates = sorted(
                    n.removeprefix("Metadata/plate_").removesuffix(".gcode")
                    for n in names
                    if n.startswith("Metadata/plate_") and n.endswith(".gcode")
                )
                if not plates:
                    raise Fail(
                        f"{path.name} に g-code が入っていません "
                        "(スライスしていない、形状だけの 3mf です)"
                    )
                raise Fail(
                    f"プレート {plate} は入っていません。入っているのは: "
                    + ", ".join(plates)
                    + " (--plate で選んでください)"
                )
            gcode = zf.read(member)
            # md5 があるなら突き合わせる。壊れたものを送らない。
            if f"{member}.md5" in names:
                want = zf.read(f"{member}.md5").decode().strip().lower()
                got = hashlib.md5(gcode).hexdigest()
                if want and want != got:
                    raise Fail(f"{member} の md5 が一致しません (ファイルが壊れています)")
    except zipfile.BadZipFile as e:
        raise Fail(f"{path.name} は 3mf (zip) として読めません") from e
    return member


# --------------------------------------------------------------------------
# サブコマンド
# --------------------------------------------------------------------------


def cmd_init(args) -> int:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        print(f"すでにあります: {CONFIG}")
        return 0
    CONFIG.write_text(
        "# Bambu プリンタの接続情報。**この repo には置かない** (アクセスコードは秘密)。\n"
        '# アクセスコードはプリンタ画面 → 設定 → ネットワーク → "アクセスコード"\n'
        "\n"
        '# default = "a1mini"\n'
        "\n"
        "[printer.a1mini]\n"
        'host = "192.168.0.1"\n'
        'serial = "00M00A000000000"\n'
        'access_code = "00000000"\n'
        '# bed_type = "textured_plate"\n',
        "utf-8",
    )
    CONFIG.chmod(0o600)
    print(f"雛形を書きました: {CONFIG} (600)")
    print("  host / serial は `bambu_send.py discover` で埋められます")
    return 0


def cmd_discover(args) -> int:
    devices = discover(args.seconds)
    if not devices:
        print("見つかりませんでした (同じ L2 セグメントに居るか、LAN モードかを確認)")
        return 1
    for d in devices:
        print(f"{d.get('name', '?')}  {d['ip']}")
        for key in ("usn", "model", "version", "connect", "bind", "signal"):
            if key in d:
                print(f"    {key:9s} {d[key]}")
    return 0


def cmd_status(args) -> int:
    printer = load_printer(args.printer)
    mqtt = Mqtt(printer)
    try:
        state = mqtt.state()
    finally:
        mqtt.close()
    keys = [
        ("gcode_state", "状態"),
        ("subtask_name", "ジョブ名"),
        ("gcode_file", "ファイル"),
        ("mc_percent", "進捗 %"),
        ("mc_remaining_time", "残り分"),
        ("print_error", "エラー"),
        ("nozzle_diameter", "ノズル径"),
        ("nozzle_temper", "ノズル温度"),
        ("bed_temper", "ベッド温度"),
        ("sdcard", "SD カード"),
    ]
    print(f"{printer.name} ({printer.host})")
    for key, label in keys:
        if key in state:
            print(f"  {pad(label, 12)} {state[key]}")
    return 0


def cmd_ls(args) -> int:
    printer = load_printer(args.printer)
    ftps = ftps_connect(printer)
    try:
        try:
            names = ftps.nlst(args.path)
        except ftplib.error_perm as e:
            raise Fail(f"{args.path} を読めません ({e})") from e
        for name in sorted(n for n in names if n):
            print(f"  {name}")
        print(f"({len(names)} 件)")
    finally:
        ftps.close()
    return 0


def _upload(printer: Printer, path: Path, remote: str) -> int:
    """FTP のルートに置き、置けたことを一覧で確かめて返す。"""
    ftps = ftps_connect(printer)
    try:
        size = path.stat().st_size
        try:
            with path.open("rb") as fp:
                ftps.storbinary(f"STOR /{remote}", fp, blocksize=32768)
        except (OSError, ftplib.Error) as e:
            # **生の例外を外に出さない。** 何が起きたかを一行で言う。
            raise Fail(f"転送に失敗しました ({type(e).__name__}: {e})") from e
        # **置いたと言う前に、在ることを確かめる。**
        # SIZE が失敗したときに黙って「成功」にしない。550 (無い) は失敗であって
        # 「検証できなかった」ではない。SIZE 自体を持たない機体 (500/502) のときだけ
        # 検証を諦め、**諦めたことを言う**。
        try:
            landed = ftps.size(f"/{remote}")
        except ftplib.error_perm as e:
            code = str(e)[:3]
            if code in ("500", "502"):
                print(f"warning: このプリンタは SIZE に答えないので大きさを検証していません ({e})")
                return size
            raise Fail(f"転送後に /{remote} を確認できませんでした ({e})") from e
        if landed is None:
            raise Fail(f"転送後に /{remote} の大きさを取得できませんでした")
        if landed != size:
            raise Fail(f"転送後の大きさが違います (手元 {size} / プリンタ {landed})")
        return size
    finally:
        ftps.close()


def cmd_upload(args) -> int:
    printer = load_printer(args.printer)
    path = Path(args.file).expanduser().resolve()
    if not path.exists():
        raise Fail(f"ファイルがありません: {path}")
    remote = args.name or path.name
    if "/" in remote:
        raise Fail("--name にディレクトリは指定できません (プリンタのルートに置きます)")
    if path.suffix.lower() == ".3mf":
        inspect_3mf(path, args.plate)  # 送る前に検査する
    size = _upload(printer, path, remote)
    print(f"置きました: /{remote} ({size:,} bytes)")
    print("  印刷は始めていません (`print` サブコマンドで開始します)")
    return 0


def cmd_print(args) -> int:
    printer = load_printer(args.printer)
    path = Path(args.file).expanduser().resolve()
    member = inspect_3mf(path, args.plate)  # 通らなければ送らない
    remote = args.name or path.name
    if "/" in remote:
        raise Fail("--name にディレクトリは指定できません")

    mqtt = Mqtt(printer)
    try:
        state = mqtt.state()
        current = str(state.get("gcode_state", "?"))
        if current not in ("IDLE", "FINISH", "FAILED"):
            raise Fail(
                f"プリンタが {current} です。実行中のジョブを潰さないため中止しました "
                "(終わってから、または手元で止めてから再実行してください)"
            )
        if not args.yes:
            # **戻せない操作なので、既定では実行しない。**
            print(f"印刷しようとしているもの: {path.name} / {member}")
            print(f"  宛先   : {printer.name} ({printer.host})")
            print(f"  ベッド : {printer.bed_type}")
            print(f"  AMS    : {'使う' if args.use_ams else '使わない'}")
            print("  → 実行するには --yes を付けてください (フィラメントを消費します)")
            return 2

        size = _upload(printer, path, remote)
        print(f"置きました: /{remote} ({size:,} bytes)")

        mqtt.publish(
            {
                "print": {
                    "command": "project_file",
                    "param": member,
                    "file": remote,
                    "url": f"ftp:///{remote}",
                    "subtask_name": path.stem,
                    "bed_type": printer.bed_type,
                    "bed_leveling": not args.no_bed_leveling,
                    "flow_cali": not args.no_flow_cali,
                    "vibration_cali": True,
                    "layer_inspect": False,
                    "timelapse": bool(args.timelapse),
                    "use_ams": bool(args.use_ams),
                    "ams_mapping": list(args.ams_mapping) if args.use_ams else [],
                    "sequence_id": "10000000",
                }
            }
        )
        print("印刷開始を指示しました。応答を見ます...")

        for message in mqtt.listen(args.watch):
            part = message.get("print")
            if not isinstance(part, dict):
                continue
            error = part.get("print_error")
            if error:
                raise Fail(f"プリンタがエラーを返しました: print_error={error}")
            state_now = part.get("gcode_state")
            if state_now and state_now not in ("IDLE", "FINISH"):
                print(f"  受理: gcode_state={state_now} / {part.get('subtask_name', '')}")
                return 0
        # **勝手に成功と言わない。**
        print(f"  {args.watch:.0f} 秒のあいだに開始が確認できませんでした。")
        print("  `bambu_send.py status` と本体の画面で確かめてください")
        return 1
    finally:
        mqtt.close()


def cmd_doctor(args) -> int:
    """3 経路をそれぞれ独立に確かめて、どこで切れているかを名指しする。"""
    ok = True
    try:
        printer = load_printer(args.printer)
    except Fail as e:
        print(f"[NG] 設定: {e}")
        return 1
    print(f"対象: {printer.name} ({printer.host}) SN={printer.serial}")

    try:
        with socket.create_connection((printer.host, FTPS_PORT), timeout=5):
            pass
        print(f"[OK] {FTPS_PORT} に到達")
    except OSError as e:
        print(f"[NG] {FTPS_PORT} に到達できません: {e}")
        ok = False

    try:
        ftps = ftps_connect(printer)
        names = [n for n in ftps.nlst("/") if n]
        ftps.close()
        print(f"[OK] FTPS ログイン (ルートに {len(names)} 件)")
    except Fail as e:
        print(f"[NG] FTPS: {e}")
        ok = False

    try:
        mqtt = Mqtt(printer)
        state = mqtt.state()
        mqtt.close()
        sd = state.get("sdcard")
        print(f"[OK] MQTT 認証 (状態 {state.get('gcode_state')} / SD {sd})")
        if sd is False:
            print("[NG] SD カードがありません。ファイルを置く先がないので印刷できません")
            ok = False
    except Fail as e:
        print(f"[NG] MQTT: {e}")
        ok = False

    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bambu_send.py", description="Bambu プリンタへ LAN 経由でファイルを送る"
    )
    parser.add_argument("--printer", help="設定内のプリンタ名 (省略時は default か唯一の 1 台)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="設定ファイルの雛形を書く")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("discover", help="LAN の Bambu 機を探す")
    p.add_argument("--seconds", type=float, default=8.0)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("doctor", help="経路ごとに疎通を確かめる")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("status", help="プリンタの状態を 1 回読む")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("ls", help="プリンタ上のファイル一覧")
    p.add_argument("path", nargs="?", default="/")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("upload", help="ファイルを置く (印刷しない)")
    p.add_argument("file")
    p.add_argument("--name", help="プリンタ側の名前 (既定は元のファイル名)")
    p.add_argument("--plate", type=int, default=1)
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("print", help="置いて印刷を始める (--yes が要る)")
    p.add_argument("file")
    p.add_argument("--name")
    p.add_argument("--plate", type=int, default=1)
    p.add_argument("--yes", action="store_true", help="実際に印刷する")
    p.add_argument("--use-ams", action="store_true")
    p.add_argument("--ams-mapping", type=int, nargs="*", default=[0])
    p.add_argument("--timelapse", action="store_true")
    p.add_argument("--no-bed-leveling", action="store_true")
    p.add_argument("--no-flow-cali", action="store_true")
    p.add_argument("--watch", type=float, default=30.0, help="開始を見届ける秒数")
    p.set_defaults(func=cmd_print)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (OSError, ftplib.Error) as e:
        # **生の例外を外に出さない。** 相手は LAN の向こうの機械なので、握手や
        # 読みが途中で止まるのは普通に起きる (実測: TLS 握手のタイムアウトが
        # トレースバックで出ていた)。何が起きたかを 1 行で言う。
        print(f"error: 通信に失敗しました ({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
