#!/usr/bin/env python3
"""yt_transcribe — YouTube 動画の音声をローカル Whisper で文字起こしする。

このスクリプトが引き受けるのは次の 4 点:

  1. 取得       — yt-dlp (CLI) でメタデータを引き、音声だけを落とす。yt-dlp は依存に入れず
                  PATH 上の CLI と利用者の設定 (~/.config/yt-dlp/config) を使う。YouTube の
                  仕様変更に追従するため頻繁に更新するツールなので、`uv tool upgrade` の
                  1 箇所で直せるようにしておく (スクリプトの依存に固めると更新が届かない)。
  2. 実行先     — GPU の空き VRAM を見て GPU / CPU を自動で選ぶ。**vLLM は止めない**
                  (他のセッションが使っているかもしれない)。空きが足りなければ CPU に落とし、
                  その旨を stderr で伝える。GPU で走り出してから OOM しても CPU でやり直す。
  3. 文字起こし — faster-whisper。モデル ID と revision は config/models.yml の
                  key: transcribe から実行時に読む (単一ソース・根拠 docs/adr/0017)。
  4. 保存       — 動画ごとのディレクトリに transcript.txt (見出し + [HH:MM:SS] 行)・
                  segments.json・meta.json を書く。書き込みは一時ファイル経由で、
                  中断しても「完成した文字起こし」に見える残骸を作らない
                  (transcript.txt の有無をキャッシュ判定に使っているため)。

外部 LLM への送信は無い。音声も文字起こしもこの機械の外に出ない。ネットワークに出るのは
動画サイトからの取得と、初回のモデル重みの取得 (HuggingFace) だけ。

Usage:
  yt_transcribe.py <URL>
  yt_transcribe.py <URL> --lang ja
  yt_transcribe.py <URL> --device cpu --keep-audio
  yt_transcribe.py <URL> --cookies-from-browser chrome   # ログインが要る動画
"""
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "faster-whisper==1.2.1",
#   "av<19",  # av 19 で open() の metadata_errors 引数が消え、faster-whisper 1.2.1 が落ちる
#   "pyyaml>=6",
# ]
# ///

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import yaml

# ~/.claude/skills の symlink 経由でも実体の repo を指す
LEDGER = Path(__file__).resolve().parents[3] / "config" / "models.yml"
LEDGER_KEY = "transcribe"
OUT_ROOT = Path(
    os.environ.get("YT_TRANSCRIBE_DIR") or Path.home() / ".local" / "share" / "yt-transcribe"
)

# 実測 (2026-10-16): large-v3 int8_float16 の VRAM ピークは 2.6GB。少し余裕を見て 3GB を要求する
GPU_MIN_FREE_MIB = 3000
# 16 と 32 スレッドで速度がほぼ同じだった (46 秒 vs 44 秒)。全コアを占有しない
CPU_THREADS = min(16, os.cpu_count() or 4)
PROGRESS_EVERY_SEC = 300  # 音声 5 分ごとに進捗を出す
DESC_CHARS = 800  # 概要欄は固有名詞の照合に使う。全文は要らない

YOUTUBE_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def log(msg: str) -> None:
    print(f"yt-transcribe: {msg}", file=sys.stderr, flush=True)


def die(msg: str, code: int = 1) -> NoReturn:
    log(msg)
    raise SystemExit(code)


def hms(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_model_entry() -> tuple[str, str]:
    """台帳から (id, revision) を読む。スクリプトに ID を直書きしない (ADR-0017)。"""
    try:
        ledger = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    except OSError as e:
        die(f"モデル台帳を読めません: {LEDGER} ({e})")
    for m in ledger.get("active", []):
        if m.get("key") == LEDGER_KEY:
            return m["id"], m["revision"]
    die(f"台帳 {LEDGER} に key: {LEDGER_KEY} がありません")


# --- 1. 取得 ---------------------------------------------------------------


def ytdlp(args: list[str], cookies: str | None) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("yt-dlp")
    if not exe:
        die("yt-dlp が見つかりません。`uv tool install 'yt-dlp[default]'` で導入してください")
    cookie_args = ["--cookies-from-browser", cookies] if cookies else []
    return subprocess.run(
        [exe, "--no-playlist", *cookie_args, *args],
        check=False, capture_output=True, text=True,
    )


def ytdlp_failed(what: str, r: subprocess.CompletedProcess[str]) -> NoReturn:
    tail = "\n".join(r.stderr.strip().splitlines()[-5:])
    die(
        f"{what}に失敗しました (yt-dlp exit {r.returncode}):\n{tail}\n"
        "  - 急に取れなくなった → `uv tool upgrade yt-dlp` (YouTube の仕様変更が多い)\n"
        "  - ログイン・年齢確認が要る → --cookies-from-browser chrome\n"
        "  - 署名・n challenge のエラー → ~/.config/yt-dlp/config の --js-runtimes を確認"
    )


def video_id(url: str, cookies: str | None) -> str:
    """保存先を決める ID。YouTube は URL から引き、ネットワークに出ずにキャッシュを判定する。"""
    if m := YOUTUBE_ID.search(url):
        return m.group(1)
    # プレイリストやチャンネルの URL だと全件を展開しに行くので、平たく 2 件までで打ち切る
    r = ytdlp(["--flat-playlist", "--playlist-end", "2", "--print", "id", url], cookies)
    if r.returncode != 0:
        ytdlp_failed("動画情報の取得", r)
    ids = r.stdout.split()
    if len(ids) != 1:
        die("動画 1 本の URL を指定してください (プレイリストやチャンネルの URL は扱いません)")
    return re.sub(r"[^\w.-]", "_", ids[0])


def download_audio(url: str, d: Path, cookies: str | None) -> tuple[Path, dict[str, Any]]:
    """音声と動画情報 (audio.info.json) を 1 回の yt-dlp 呼び出しで取る。

    情報取得とダウンロードを分ける (-J → --load-info-json) と、取得時に選ばれた
    クライアントの URL が 403 になったとき yt-dlp が別クライアントに切り替えられない
    (2026-10-16 に実際に 403 で落ちた)。1 回で取らせて再試行を yt-dlp に任せる。
    """
    info_path = d / "audio.info.json"

    def finished() -> list[Path]:
        return [p for p in sorted(d.glob("audio.*")) if p.suffix not in (".part", ".ytdl", ".json")]

    # 前回の実行が文字起こしの途中で落ちていれば、落とし直さずに使う
    if not ((found := finished()) and info_path.exists()):
        r = ytdlp(
            ["-f", "bestaudio/best", "--write-info-json", "--match-filter", "!is_live",
             "-o", str(d / "audio.%(ext)s"), "--print", "after_move:filepath", url],
            cookies,
        )
        if r.returncode != 0:
            ytdlp_failed("音声のダウンロード", r)
        if not r.stdout.strip():
            die("ダウンロードされませんでした。配信中のライブは扱えません (配信終了後のアーカイブを指定)")
        found = finished()
    if not found or not info_path.exists():
        die(f"音声ファイルか動画情報が見つかりません: {d}")
    return found[0], json.loads(info_path.read_text(encoding="utf-8"))


# --- 2. 実行先 -------------------------------------------------------------


def pick_device(requested: str) -> tuple[str, int]:
    """(device, device_index) を返す。vLLM には一切触らない。"""
    if requested == "cpu":
        return "cpu", 0
    import ctranslate2

    gpus: list[tuple[int, int]] = []  # (空き MiB, index)
    if ctranslate2.get_cuda_device_count() > 0 and (smi := shutil.which("nvidia-smi")):
        r = subprocess.run(
            [smi, "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
            check=False, capture_output=True, text=True,
        )
        for line in r.stdout.splitlines():
            i, mib = (x.strip() for x in line.split(","))
            gpus.append((int(mib), int(i)))
    if not gpus:
        if requested == "cuda":
            die("--device cuda が指定されましたが、使える GPU がありません")
        log("GPU が見つからないため CPU で実行します")
        return "cpu", 0
    free, idx = max(gpus)
    if free >= GPU_MIN_FREE_MIB or requested == "cuda":
        return "cuda", idx
    log(
        f"GPU の空きが {free} MiB で足りません (必要 {GPU_MIN_FREE_MIB} MiB)。CPU で実行します "
        "(目安: 音声の長さの 1/5 ほど)。vLLM などの GPU 利用には触っていません"
    )
    return "cpu", 0


# --- 3. 文字起こし ---------------------------------------------------------


def transcribe(
    audio: Path, model_id: str, revision: str, device: str, device_index: int, lang: str | None
) -> tuple[list[dict[str, Any]], Any, str]:
    from faster_whisper import WhisperModel

    compute = "int8_float16" if device == "cuda" else "int8"
    model = WhisperModel(
        model_id, device=device, device_index=device_index, compute_type=compute,
        revision=revision, cpu_threads=CPU_THREADS if device == "cpu" else 0,
    )
    # condition_on_previous_text=False: 前文脈を引き継ぐと decoder の系列が伸び、
    # vLLM 常駐下では OOM した (実測)。長尺での同じ文の繰り返し (幻覚ループ) も抑えられる
    it, info = model.transcribe(
        str(audio), language=lang, vad_filter=True, beam_size=5,
        condition_on_previous_text=False,
    )
    segments: list[dict[str, Any]] = []
    next_report = PROGRESS_EVERY_SEC
    for s in it:
        if text := s.text.strip():
            segments.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        if s.end >= next_report:
            log(f"進捗 {hms(s.end)} / {hms(info.duration)} ({s.end / info.duration:.0%})")
            next_report = int(s.end) + PROGRESS_EVERY_SEC
    return segments, info, compute


def is_cuda_oom(e: BaseException) -> bool:
    return isinstance(e, RuntimeError) and "out of memory" in str(e).lower()


# --- 4. 保存 ---------------------------------------------------------------


def render(meta: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    t = meta["transcription"]
    out = [
        f"# {meta['title']}",
        "",
        f"- チャンネル: {meta['channel']} / 公開日: {meta['upload_date']} / 長さ: {hms(meta['duration'])}",
        f"- URL: {meta['url']}",
    ]
    if meta.get("time_link"):
        out.append(f"- 時刻リンク: {meta['time_link']}  (<秒> に開始秒を入れる)")
    out.append(
        f"- 文字起こし: {t['model']} ({t['device']}/{t['compute_type']}) / "
        f"言語 {t['language']} (確率 {t['language_probability']:.2f}) / {t['elapsed_sec']} 秒"
    )
    if meta["chapters"]:
        out += ["", "## チャプター", ""]
        out += [f"- [{hms(c['start'])}] {c['title']}" for c in meta["chapters"]]
    if meta["description"]:
        out += ["", f"## 概要欄 (先頭 {DESC_CHARS} 字・固有名詞の照合用)", "", meta["description"]]
    out += ["", "## 本文", ""]
    out += [f"[{hms(s['start'])}] {s['text']}" for s in segments]
    return "\n".join(out) + "\n"


def report(path: Path, meta: dict[str, Any], cached: bool) -> None:
    t = meta["transcription"]
    print(f"transcript: {path}")
    print(f"title: {meta['title']}")
    print(
        f"duration: {hms(meta['duration'])}  segments: {t['segments']}  "
        f"device: {t['device']}/{t['compute_type']}  elapsed: {t['elapsed_sec']}s"
        + ("  (キャッシュ)" if cached else "")
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="YouTube 動画をローカル Whisper で文字起こしする")
    ap.add_argument("url", help="動画の URL (YouTube 以外も yt-dlp が対応していれば可)")
    ap.add_argument("--lang", help="言語コード (例: ja)。省略時は冒頭 30 秒から自動判定")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    ap.add_argument("--keep-audio", action="store_true", help="文字起こし後も音声を残す")
    ap.add_argument("--force", action="store_true", help="キャッシュがあっても文字起こしし直す")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER", help="yt-dlp にそのまま渡す")
    args = ap.parse_args()

    d = OUT_ROOT / video_id(args.url, args.cookies_from_browser)
    if not args.force and (d / "transcript.txt").exists() and (d / "meta.json").exists():
        report(d / "transcript.txt", json.loads((d / "meta.json").read_text("utf-8")), True)
        return

    model_id, revision = load_model_entry()
    d.mkdir(parents=True, exist_ok=True)
    log(f"音声を取得中: {args.url}")
    audio, info = download_audio(args.url, d, args.cookies_from_browser)
    log(f"取得済み: {info.get('title')} ({hms(info.get('duration') or 0)})")

    device, idx = pick_device(args.device)
    log(f"文字起こし中: {model_id} on {device}")
    t0 = time.time()
    result = None
    try:
        result = transcribe(audio, model_id, revision, device, idx, args.lang)
    except RuntimeError as e:
        if device != "cuda" or not is_cuda_oom(e) or args.device == "cuda":
            raise
    if result is None:
        # except 節の外でやり直す: 例外の traceback が GPU 上のモデルを掴んだままにしないため
        log("GPU のメモリが途中で足りなくなりました (他のプロセスが確保した可能性)。CPU でやり直します")
        gc.collect()
        device = "cpu"
        result = transcribe(audio, model_id, revision, device, 0, args.lang)
    segments, winfo, compute = result
    elapsed = round(time.time() - t0)

    if not args.lang and winfo.language_probability < 0.7:
        log(
            f"言語の自動判定が不確か ({winfo.language} / {winfo.language_probability:.2f})。"
            "冒頭が音楽などの場合は --lang ja のように指定してやり直してください (--force)"
        )

    vid = str(info["id"])
    is_youtube = info.get("extractor_key") == "Youtube"
    upload = str(info.get("upload_date") or "")
    meta = {
        "id": vid,
        "url": info.get("webpage_url") or args.url,
        "time_link": f"https://youtu.be/{vid}?t=<秒>" if is_youtube else None,
        "title": info.get("title") or vid,
        "channel": info.get("channel") or info.get("uploader") or "-",
        "upload_date": f"{upload[:4]}-{upload[4:6]}-{upload[6:]}" if len(upload) == 8 else "-",
        "duration": info.get("duration") or winfo.duration,
        "chapters": [
            {"start": c.get("start_time", 0), "title": c.get("title", "")}
            for c in info.get("chapters") or []
        ],
        "description": (info.get("description") or "")[:DESC_CHARS].strip(),
        "transcription": {
            "model": model_id,
            "revision": revision,
            "device": device,
            "compute_type": compute,
            "language": winfo.language,
            "language_probability": round(winfo.language_probability, 3),
            "segments": len(segments),
            "elapsed_sec": elapsed,
            "transcribed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    }
    # transcript.txt をキャッシュの印にしているので最後に書く
    write_atomic(d / "segments.json", json.dumps(segments, ensure_ascii=False, indent=1))
    write_atomic(d / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    write_atomic(d / "transcript.txt", render(meta, segments))
    # 動画情報は全フォーマットの一覧を含み大きい。要る項目は meta.json に写した
    (d / "audio.info.json").unlink(missing_ok=True)
    if not args.keep_audio:
        audio.unlink(missing_ok=True)
    report(d / "transcript.txt", meta, False)


if __name__ == "__main__":
    main()
