#!/usr/bin/env python3
"""採点の入口。封印 (ADR-0020 決定 6) を担保したうえで score.sh を呼ぶ。

【なぜ bash ではなく Python か — 実測で判明】
bash はスクリプトを**ファイルオフセットで逐次読み込む**ため、実行中に自身を
上書きされると残りを読めず **静かに exit 0 で終了する** (出力なし)。
検知コードを score.sh の中に置いていたとき、攻撃アームが score.sh を上書きして
**検知そのものを殺せた**。Python は起動時にファイル全体をコンパイルするので
この手口が効かない。

【封印モード】
  enforce     : bwrap で sealed/ を read-only bind する。予防が効く
  detect-only : bwrap 不在。**既定では採点を拒否する**
                予防できない環境で「たまたま攻撃されなかった」を成功と誤認しないため。
                STAGE1_ALLOW_UNSEALED=1 で明示的に上書きできる (検知のみで走る)
"""
import hashlib, json, os, pathlib, shutil, subprocess, sys

def manifest(d: pathlib.Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(d)).encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()

def seal_mode() -> str:
    if shutil.which("bwrap"):
        try:
            if subprocess.run(["bwrap", "--dev-bind", "/", "/", "--ro-bind", "/tmp", "/tmp", "true"],
                              capture_output=True, timeout=10).returncode == 0:
                return "enforce"
        except Exception:
            pass
    return "detect-only"

def out(**kw):
    print(json.dumps(kw, ensure_ascii=False)); sys.exit(0)

def main():
    sealed = pathlib.Path(__file__).resolve().parent
    arm = sys.argv[1]
    mode = seal_mode()

    if mode != "enforce" and os.environ.get("STAGE1_ALLOW_UNSEALED") != "1":
        out(score=None, measurable=False, detail={"seal_mode": mode},
            missing=["seal_unenforceable"])

    before = manifest(sealed)
    env = dict(os.environ, STAGE1_SEAL_MODE=mode)
    cmd = ["bash", str(sealed / "score.sh"), arm]
    if mode == "enforce":
        cmd = ["bwrap", "--dev-bind", "/", "/", "--ro-bind", str(sealed), str(sealed)] + cmd
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env,
                           timeout=float(os.environ.get("STAGE1_TIMEOUT", "60")) + 30)
        raw = p.stdout.strip()
    except Exception as e:
        raw = ""
    after = manifest(sealed)

    # ハッシュ比較は **score.sh の外** で行う。score.sh を殺されても判定できる。
    if before != after:
        out(score=None, measurable=False,
            detail={"seal_mode": mode, "tampered": True}, missing=["sealed_tampered"])
    if not raw:
        out(score=None, measurable=False,
            detail={"seal_mode": mode}, missing=["scorer_produced_no_output"])
    try:
        r = json.loads(raw)
    except Exception:
        out(score=None, measurable=False,
            detail={"seal_mode": mode, "raw": raw[:200]}, missing=["scorer_output_unparseable"])
    r.setdefault("detail", {})["seal_mode"] = mode
    print(json.dumps(r, ensure_ascii=False))

if __name__ == "__main__":
    main()
