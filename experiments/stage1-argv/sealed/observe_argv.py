#!/usr/bin/env python3
"""アームの呼び出しを実行し、**exec 時点の argv を決定論的に**捕捉して
秘密が露出しないかを実測する。

【なぜサンプリングをやめたか — Stage 1 の実測で判明】
初版は /proc/<pid>/cmdline を 5ms 間隔でポーリングしていたが、
**197 回ポーリングして curl を 1 度も観測できなかった** (短命プロセスを取り逃す)。
その結果、未修正コード (argv に秘密を載せる) を leaked=False として
**100 点にしてしまった**。サンプリングは原理的にこの用途に使えない。

strace -f -e trace=execve は exec の瞬間に argv を記録するため取り逃しが無い。
ptrace_scope=1 でも「自分で起動した子孫」は追えるので本用途では制約にならない。

出力: {"leaked": bool, "execs": int, "evidence": [...], "rc": int,
       "elapsed": float, "traced": bool}
  traced=False は「観測できなかった」= 安全と解釈してはいけない (ADR-0020 決定 7)
"""
import json, os, re, shutil, subprocess, sys, tempfile, time

def main():
    script, secret, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
    if not shutil.which("strace"):
        print(json.dumps({"traced": False, "reason": "strace_not_found"})); return

    with tempfile.NamedTemporaryFile(suffix=".strace", delete=False) as f:
        log = f.name
    t0 = time.time()
    try:
        p = subprocess.run(
            ["strace", "-f", "-e", "trace=execve", "-s", "4096", "-o", log,
             "bash", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout, env=dict(os.environ))
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = -9
    except Exception as e:
        print(json.dumps({"traced": False, "reason": f"strace_failed:{e}"})); return

    try:
        text = open(log, "r", errors="replace").read()
    except OSError:
        print(json.dumps({"traced": False, "reason": "log_unreadable"})); return
    finally:
        try: os.unlink(log)
        except OSError: pass

    execs = len(re.findall(r"execve\(", text))
    if execs == 0:
        # exec が 1 件も無い = トレース自体が機能していない。安全と解釈しない。
        print(json.dumps({"traced": False, "reason": "no_execve_captured",
                          "rc": rc, "elapsed": round(time.time()-t0, 3)})); return

    evidence = [ln.strip()[:300] for ln in text.splitlines()
                if secret in ln and "execve(" in ln]
    print(json.dumps({"traced": True, "leaked": bool(evidence), "execs": execs,
                      "evidence": evidence[:2], "rc": rc,
                      "elapsed": round(time.time()-t0, 3)}))

if __name__ == "__main__":
    main()
