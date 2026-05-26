"""Webcam Jetson — aiohttp HTTP API on top of mediamtx RTSP.

Endpoints:
  GET  /healthz                          → JSON health (device / mediamtx paths / active recordings)
  GET  /snapshot.jpg[?w=W&h=H]           → single JPEG frame (ffmpeg -frames:v 1)
  GET  /stream.mjpg                      → multipart/x-mixed-replace MJPEG (ffmpeg -f mpjpeg)
  POST /record?duration=N&format=mkv|mp4 → start recording, returns {id, filename, ...}
  GET  /recordings                       → list saved files
  GET  /recordings/<name>                → download a saved file

Configuration via env vars (with defaults):
  WCAM_RTSP_URL        rtsp://127.0.0.1:8554/cam
  WCAM_REC_DIR         /var/lib/webcam-jetson/recordings
  WCAM_MAX_RECORDINGS  50
  WCAM_LISTEN          0.0.0.0
  WCAM_PORT            8080
  WCAM_VIDEO_DEV       /dev/video0
  WCAM_MEDIAMTX_API    http://127.0.0.1:9997
"""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web


RTSP_URL = os.getenv("WCAM_RTSP_URL", "rtsp://127.0.0.1:8554/cam")
REC_DIR = Path(os.getenv("WCAM_REC_DIR", "/var/lib/webcam-jetson/recordings"))
MAX_RECORDINGS = int(os.getenv("WCAM_MAX_RECORDINGS", "50"))
LISTEN_HOST = os.getenv("WCAM_LISTEN", "0.0.0.0")
LISTEN_PORT = int(os.getenv("WCAM_PORT", "8080"))
VIDEO_DEV = os.getenv("WCAM_VIDEO_DEV", "/dev/video0")
MEDIAMTX_API = os.getenv("WCAM_MEDIAMTX_API", "http://127.0.0.1:9997")

REC_DIR.mkdir(parents=True, exist_ok=True)

# Tracks in-flight ffmpeg recordings: id -> {path, duration, format, started, proc}
active_recordings: dict[str, dict] = {}


async def healthz(request: web.Request) -> web.Response:
    cam_ok = Path(VIDEO_DEV).exists()
    try:
        async with request.app["session"].get(
            f"{MEDIAMTX_API}/v3/paths/list", timeout=aiohttp.ClientTimeout(total=2)
        ) as r:
            body = await r.json()
            mtx_paths = {
                p["name"]: {
                    "ready": p.get("ready", False),
                    "tracks": p.get("tracks", []),
                    "bytesReceived": p.get("bytesReceived"),
                }
                for p in body.get("items", [])
            }
            mtx_error = None
    except Exception as e:
        mtx_paths = {}
        mtx_error = str(e)

    return web.json_response(
        {
            "video_device": VIDEO_DEV,
            "video_device_exists": cam_ok,
            "rtsp_url": RTSP_URL,
            "mediamtx_api": MEDIAMTX_API,
            "mediamtx_paths": mtx_paths,
            "mediamtx_error": mtx_error,
            "active_recordings": list(active_recordings.keys()),
            "recordings_dir": str(REC_DIR),
        }
    )


async def snapshot(request: web.Request) -> web.Response:
    width = request.query.get("w")
    height = request.query.get("h")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", RTSP_URL,
        "-frames:v", "1",
    ]
    if width and height:
        try:
            w, h = int(width), int(height)
            cmd += ["-vf", f"scale={w}:{h}"]
        except ValueError:
            return web.Response(status=400, text="w/h must be integers")
    cmd += ["-f", "image2", "-c:v", "mjpeg", "-q:v", "3", "pipe:1"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return web.Response(status=504, text="ffmpeg timeout")

    if proc.returncode != 0 or not stdout:
        return web.Response(
            status=502,
            text=f"ffmpeg failed (rc={proc.returncode}): {stderr.decode(errors='replace')[:500]}",
        )
    return web.Response(body=stdout, content_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


async def stream_mjpg(request: web.Request) -> web.StreamResponse:
    boundary = "ffmpeg"
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
            "Cache-Control": "no-cache",
            "Connection": "close",
        },
    )
    await response.prepare(request)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", RTSP_URL,
        "-f", "mpjpeg", "-q:v", "5", "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        while True:
            chunk = await proc.stdout.read(64 * 1024)
            if not chunk:
                break
            try:
                await response.write(chunk)
            except (ConnectionResetError, asyncio.CancelledError):
                break
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return response


async def record(request: web.Request) -> web.Response:
    try:
        duration = int(request.query.get("duration", "10"))
    except ValueError:
        return web.Response(status=400, text="duration must be integer seconds")
    fmt = request.query.get("format", "mkv").lower()
    if fmt not in ("mkv", "mp4"):
        return web.Response(status=400, text="format must be mkv or mp4")
    if not (1 <= duration <= 3600):
        return web.Response(status=400, text="duration must be 1..3600 seconds")

    rid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    out_path = REC_DIR / f"{rid}.{fmt}"

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", "tcp", "-i", RTSP_URL,
        "-t", str(duration),
    ]
    if fmt == "mp4":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    else:
        cmd += ["-c", "copy"]
    cmd += ["-y", str(out_path)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    active_recordings[rid] = {
        "id": rid,
        "path": str(out_path),
        "filename": out_path.name,
        "duration": duration,
        "format": fmt,
        "started": time.time(),
    }

    async def wait_and_cleanup():
        try:
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                print(f"[record {rid}] ffmpeg rc={proc.returncode}: "
                      f"{stderr.decode(errors='replace')[:500]}")
        finally:
            active_recordings.pop(rid, None)
            _trim_old_recordings()

    asyncio.create_task(wait_and_cleanup())

    return web.json_response(
        {
            "id": rid,
            "filename": out_path.name,
            "duration": duration,
            "format": fmt,
            "url": f"/recordings/{out_path.name}",
        },
        status=202,
    )


def _trim_old_recordings() -> None:
    files = sorted(REC_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[MAX_RECORDINGS:]:
        try:
            f.unlink()
        except OSError:
            pass


async def list_recordings(request: web.Request) -> web.Response:
    in_flight = {Path(r["path"]).name for r in active_recordings.values()}
    files = sorted(REC_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return web.json_response(
        [
            {
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                "in_progress": f.name in in_flight,
                "url": f"/recordings/{f.name}",
            }
            for f in files
        ]
    )


async def get_recording(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if "/" in name or "\\" in name or name.startswith("."):
        return web.Response(status=400, text="invalid name")
    p = REC_DIR / name
    if not p.exists() or not p.is_file():
        return web.Response(status=404, text="not found")
    in_flight = {Path(r["path"]).name for r in active_recordings.values()}
    if name in in_flight:
        return web.Response(status=409, text="recording still in progress")
    return web.FileResponse(p)


async def _ptz_get() -> dict:
    cmd = ["v4l2-ctl", "--device", VIDEO_DEV,
           "--get-ctrl=zoom_absolute,pan_absolute,tilt_absolute"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate()
    raw: dict[str, int] = {}
    for line in out.decode(errors="replace").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            try:
                raw[k.strip()] = int(v.strip())
            except ValueError:
                pass
    return {
        "zoom": raw.get("zoom_absolute", 100) / 100.0,
        "pan_percent": raw.get("pan_absolute", 0) / 360.0,
        "tilt_percent": raw.get("tilt_absolute", 0) / 360.0,
        "raw": raw,
    }


async def ptz(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response(await _ptz_get())

    params = request.rel_url.query
    sets: list[str] = []
    if params.get("reset", "").lower() in ("1", "true", "yes"):
        sets = ["zoom_absolute=100", "pan_absolute=0", "tilt_absolute=0"]
    else:
        if "zoom" in params:
            try:
                z = float(params["zoom"])
            except ValueError:
                return web.Response(status=400, text="zoom must be number 1.0..5.0")
            if not (1.0 <= z <= 5.0):
                return web.Response(status=400, text="zoom out of range 1.0..5.0")
            sets.append(f"zoom_absolute={int(round(z * 100))}")
        for axis in ("pan", "tilt"):
            if axis in params:
                try:
                    pct = float(params[axis])
                except ValueError:
                    return web.Response(
                        status=400, text=f"{axis} must be number -100..100 (percent)")
                if not (-100 <= pct <= 100):
                    return web.Response(status=400, text=f"{axis} out of range -100..100")
                raw_val = round(pct * 360 / 3600) * 3600  # snap to step 3600
                sets.append(f"{axis}_absolute={raw_val}")
        if not sets:
            return web.Response(
                status=400,
                text="provide at least one of zoom/pan/tilt (or reset=1)",
            )

    cmd = ["v4l2-ctl", "--device", VIDEO_DEV]
    for s in sets:
        cmd += [f"--set-ctrl={s}"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        return web.Response(
            status=502,
            text=f"v4l2-ctl failed (rc={proc.returncode}): {err.decode(errors='replace')[:500]}",
        )
    return web.json_response(await _ptz_get())


async def on_startup(app: web.Application) -> None:
    app["session"] = aiohttp.ClientSession()


async def on_cleanup(app: web.Application) -> None:
    await app["session"].close()


def make_app() -> web.Application:
    app = web.Application(client_max_size=1024 * 1024)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/snapshot.jpg", snapshot)
    app.router.add_get("/stream.mjpg", stream_mjpg)
    app.router.add_post("/record", record)
    app.router.add_get("/recordings", list_recordings)
    app.router.add_get("/recordings/{name}", get_recording)
    app.router.add_get("/ptz", ptz)
    app.router.add_post("/ptz", ptz)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    print(f"[webcam-server] listening {LISTEN_HOST}:{LISTEN_PORT}, RTSP={RTSP_URL}, recs={REC_DIR}", flush=True)
    # reuse_address: systemd 再起動ループ中に TIME_WAIT の socket が残っていても bind できるように。
    web.run_app(make_app(), host=LISTEN_HOST, port=LISTEN_PORT,
                access_log=None, reuse_address=True)
