#!/usr/bin/env python3
"""nano_banana — Gemini の画像モデル (Nano Banana 系) で画像を生成 / 編集する。

このスクリプトが引き受けるのは次の 4 点:

  1. キー解決の非常口     — GEMINI_API_KEY が「明示的に空」なら fallback せず中止する。
                            機密案件でクラウド送信を止めるための非常口で、
                            skills/gemini-review と同じ規約に揃えてある。
                            未設定 (unset) なら ~/.gemini_token に落ちる。
  2. 生成と編集の統一     — --ref を付ければ参照画像 + 指示の「編集」、無ければ
                            テキストのみの「生成」。API 上はどちらも generateContent で、
                            parts に inline_data を足すかどうかの差でしかない。
  3. 応答の取り出し       — 画像は candidates[].content.parts[].inlineData に base64 で
                            返る。テキストが混ざることもあるので両方拾う。
  4. 保存と命名           — 既定は ./nano-banana/<timestamp>-<slug>[-N].<ext>。
                            --out でファイル名を直接指定もできる。

モデル ID は config/models.yml が単一ソース (根拠: docs/adr/0017)。ここに書いてある
既定値は台帳の active と一致していなければならず、ズレたら scripts/model-doctor.sh と
CI (model-drift.yml) が落とす。**変えるときは台帳を先に直すこと。**

  gemini-3.1-flash-image  = Nano Banana 2   (既定)
  gemini-3-pro-image      = Nano Banana Pro (--pro / 高品質・文字描画に強い)

Usage:
  nano_banana.py "夕暮れの港に停まる木造船" --aspect 16:9
  nano_banana.py "背景を夜にして" --ref before.png
  nano_banana.py "ロゴを入れた告知バナー" --pro --size 2K --aspect 16:9
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import httpx

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# config/models.yml の active と一致させること (単一ソースは台帳)
MODEL_DEFAULT = "gemini-3.1-flash-image"  # Nano Banana 2
MODEL_PRO = "gemini-3-pro-image"  # Nano Banana Pro

ASPECTS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
SIZES = ["1K", "2K", "4K"]

TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)


def die(msg: str, code: int = 1) -> None:
    print(f"nano-banana: {msg}", file=sys.stderr)
    raise SystemExit(code)


def resolve_api_key() -> str:
    """GEMINI_API_KEY → ~/.gemini_token の順。明示的な空は「中止」の意思表示として扱う。"""
    if "GEMINI_API_KEY" in os.environ:
        key = os.environ["GEMINI_API_KEY"].strip()
        if not key:
            die(
                "GEMINI_API_KEY が明示的に空です。クラウド送信を行わずに中止しました。\n"
                "         (機密案件用の非常口です。送信して良い場合は変数を unset してください)"
            )
        return key

    token_file = Path.home() / ".gemini_token"
    if token_file.is_file():
        key = token_file.read_text(encoding="utf-8").strip()
        if key:
            return key
        die(f"{token_file} が空です")

    die(
        "API キーが見つかりません。GEMINI_API_KEY を設定するか、\n"
        "         ~/.gemini_token (chmod 600) に保存してください。\n"
        "         取得: https://aistudio.google.com/apikey"
    )
    raise AssertionError("unreachable")


def slugify(text: str, limit: int = 40) -> str:
    """日本語プロンプトでも壊れないファイル名を作る。ASCII 化できなければ連番だけに落とす。"""
    norm = unicodedata.normalize("NFKD", text)
    ascii_only = norm.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:limit] or "image"


def load_ref(path: Path) -> dict:
    if not path.is_file():
        die(f"参照画像が見つかりません: {path}")
    mime, _ = mimetypes.guess_type(path.name)
    if mime is None or not mime.startswith("image/"):
        die(f"画像として認識できません: {path} (mime={mime})")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"inline_data": {"mime_type": mime, "data": data}}


def build_payload(
    prompt: str, refs: list[Path], aspect: str | None, size: str | None
) -> dict:
    parts: list[dict] = [{"text": prompt}]
    # 参照画像はテキストの後ろに積む。順序は指示 → 素材の並びが安定する。
    parts.extend(load_ref(p) for p in refs)

    gen_cfg: dict = {"responseModalities": ["TEXT", "IMAGE"]}
    image_cfg: dict = {}
    if aspect:
        image_cfg["aspectRatio"] = aspect
    if size:
        image_cfg["imageSize"] = size
    if image_cfg:
        gen_cfg["imageConfig"] = image_cfg

    return {"contents": [{"parts": parts}], "generationConfig": gen_cfg}


def call_api(model: str, payload: dict, key: str) -> dict:
    url = f"{API_ROOT}/{model}:generateContent"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url, params={"key": key}, json=payload)
    except httpx.HTTPError as e:
        die(f"API 呼び出しに失敗: {e}")

    if r.status_code != 200:
        detail = r.text[:800]
        die(f"API がエラーを返しました (HTTP {r.status_code}):\n{detail}")
    return r.json()


def extract(resp: dict) -> tuple[list[tuple[bytes, str]], list[str]]:
    """(画像バイト列, mime) のリストと、混ざって返ったテキストを取り出す。"""
    images: list[tuple[bytes, str]] = []
    texts: list[str] = []

    for cand in resp.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                mime = blob.get("mimeType") or blob.get("mime_type") or "image/png"
                images.append((base64.b64decode(blob["data"]), mime))
            elif "text" in part:
                texts.append(part["text"])

        # 画像が 0 枚のとき、理由は finishReason にしか出ないことがある
        if not images and cand.get("finishReason") not in (None, "STOP"):
            texts.append(f"[finishReason={cand['finishReason']}]")

    if fb := resp.get("promptFeedback", {}).get("blockReason"):
        texts.append(f"[blockReason={fb}]")

    return images, texts


def save(
    images: list[tuple[bytes, str]], outdir: Path, out: Path | None, slug: str, seq: int
) -> list[Path]:
    saved: list[Path] = []
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")

    for i, (data, mime) in enumerate(images):
        ext = mimetypes.guess_extension(mime) or ".png"
        if ext == ".jpe":
            ext = ".jpg"

        if out is not None and len(images) == 1 and seq == 1:
            path = out
        else:
            suffix = (
                ""
                if (len(images) == 1 and seq == 1)
                else f"-{seq}{'' if len(images) == 1 else f'_{i + 1}'}"
            )
            path = outdir / f"{stamp}-{slug}{suffix}{ext}"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        saved.append(path)

    return saved


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="nano_banana.py",
        description="Nano Banana 系モデルで画像を生成 / 編集する",
    )
    ap.add_argument("prompt", help="生成 / 編集の指示")
    ap.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="PATH",
        help="参照画像 (複数可)。指定すると編集モードになる",
    )
    ap.add_argument(
        "--pro",
        action="store_true",
        help=f"Nano Banana Pro ({MODEL_PRO}) を使う。高品質・文字描画に強い",
    )
    ap.add_argument(
        "--model",
        metavar="ID",
        help="モデル ID を直接指定 (debug 用。通常は台帳の既定に従う)",
    )
    ap.add_argument(
        "--aspect",
        choices=ASPECTS,
        metavar="RATIO",
        help=f"アスペクト比 ({'/'.join(ASPECTS)})",
    )
    ap.add_argument(
        "--size",
        choices=SIZES,
        metavar="SIZE",
        help=f"解像度 ({'/'.join(SIZES)})。Pro のみ有効",
    )
    ap.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        metavar="N",
        help="生成枚数。API を N 回呼ぶ (既定 1)",
    )
    ap.add_argument(
        "--outdir",
        type=Path,
        default=Path("./nano-banana"),
        help="出力ディレクトリ (既定 ./nano-banana)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        metavar="PATH",
        help="出力ファイル名を直接指定 (1 枚のときのみ)",
    )
    ap.add_argument("--json", action="store_true", help="結果を JSON で出力する")
    args = ap.parse_args()

    if args.count < 1:
        die("-n は 1 以上を指定してください")
    if args.size and not args.pro and not args.model:
        print(
            "nano-banana: 警告 — --size は Pro 向けの指定です。無視される場合があります",
            file=sys.stderr,
        )

    model = args.model or (MODEL_PRO if args.pro else MODEL_DEFAULT)
    refs = [Path(p).expanduser() for p in args.ref]
    key = resolve_api_key()
    payload = build_payload(args.prompt, refs, args.aspect, args.size)
    slug = slugify(args.prompt)

    all_saved: list[Path] = []
    all_texts: list[str] = []

    for seq in range(1, args.count + 1):
        resp = call_api(model, payload, key)
        images, texts = extract(resp)
        all_texts.extend(texts)

        if not images:
            reason = " / ".join(texts) if texts else "(理由の記載なし)"
            die(f"画像が返りませんでした: {reason}")

        all_saved.extend(save(images, args.outdir, args.out, slug, seq))

    if args.json:
        print(
            json.dumps(
                {
                    "model": model,
                    "mode": "edit" if refs else "generate",
                    "images": [str(p) for p in all_saved],
                    "text": all_texts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        mode = "編集" if refs else "生成"
        print(f"{mode} 完了 ({model}) — {len(all_saved)} 枚")
        for p in all_saved:
            print(f"  {p}")
        for t in all_texts:
            if t.strip():
                print(f"  [model] {t.strip()[:400]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
