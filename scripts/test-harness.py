#!/usr/bin/env python3
"""test-harness.py — 外部送信の検知 (scripts/harness.py・curl-secret.sh) の回帰テスト (ADR-0023)。

検知器が壊れても実行時エラーにはならず「警告が出ない」だけになるため、目視ではなく機械で押さえる。
実際の送信はしない (curl は PATH 上の偽物に差し替える)。

    python3 scripts/test-harness.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "scripts" / "harness.py"
CURL_SECRET = REPO / "scripts" / "lib" / "curl-secret.sh"


def sh(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)


class HarnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="harness-test-"))
        cls.env = dict(os.environ)
        cls.env.update({
            "HOME": str(cls.tmp / "home"),
            "XDG_CONFIG_HOME": str(cls.tmp / "home" / ".config"),
            "XDG_STATE_HOME": str(cls.tmp / "home" / ".local" / "state"),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        })
        cls.env.pop("HARNESS_EGRESS_TARGETS", None)
        (cls.tmp / "home").mkdir()
        cls.root = cls.tmp / "repos"
        cls.decl_dir = cls.tmp / "home" / ".config" / "agent-rules" / "harness"
        cls.log = cls.tmp / "home" / ".local" / "state" / "agent-rules" / "egress.log"

        def repo(name, origin, harness_yml=None, local=None):
            d = cls.root / "github.com" / origin.split("/")[-2] / name
            d.mkdir(parents=True)
            sh(["git", "init", "-q"], d, cls.env)
            sh(["git", "remote", "add", "origin", origin], d, cls.env)
            (d / "README").write_text("x")
            if harness_yml is not None:
                (d / ".harness.yml").write_text(harness_yml)
            sh(["git", "add", "-A"], d, cls.env)
            sh(["git", "commit", "-qm", "init"], d, cls.env)
            if local is not None:
                rid = origin.replace("git@github.com:", "github.com/").replace("https://", "").removesuffix(".git")
                p = cls.decl_dir / f"{rid}.yml"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(local)
            return d

        cls.pub = repo("pub", "git@github.com:acme/pub.git", "harness: 1\nsensitivity: public\n")
        cls.internal = repo("inner", "https://github.com/acme/inner.git", "harness: 1\nsensitivity: internal\n")
        cls.conf = repo("secret", "https://github.com/client/secret", local="harness: 1\nsensitivity: confidential\n")
        cls.both = repo("both", "git@github.com:client/both.git", "harness: 1\nsensitivity: public\n",
                        local="harness: 1\nsensitivity: confidential\n")
        cls.undecl = repo("plain", "git@github.com:acme/plain.git")
        cls.bad = repo("bad", "git@github.com:acme/bad.git", "harness: 1\nsensitivity: [unclosed\n")
        cls.unrelated = repo("unrelated", "git@github.com:acme/unrelated.git", "pipeline:\n  name: ci\n")
        cls.unknownval = repo("weird", "git@github.com:acme/weird.git", "harness: 1\nsensitivity: secret\n")
        cls.wrongtype = repo("typed", "git@github.com:acme/typed.git", "harness: 1\nsensitivity: [public]\n")
        cls.wt = cls.tmp / "wt"
        sh(["git", "worktree", "add", "-q", str(cls.wt), "-b", "feat"], cls.conf, cls.env)
        cls.outside = cls.tmp / "outside"
        cls.outside.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --- helpers ---
    def check(self, cwd, *args, env_extra=None):
        env = dict(self.env)
        env.update(env_extra or {})
        return sh([sys.executable, str(HARNESS), "egress-check", *args], cwd, env)

    def resolve(self, path):
        r = sh([sys.executable, str(HARNESS), "resolve", str(path)], self.tmp, self.env)
        return json.loads(r.stdout)

    def log_lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    # --- 区分の解決 (§4-1) ---
    def test_resolve_declared_and_strictest_wins(self):
        self.assertEqual(self.resolve(self.pub)["level"], "public")
        self.assertEqual(self.resolve(self.conf)["level"], "confidential")
        both = self.resolve(self.both)  # AC-5: repo=public・ローカル=confidential → confidential
        self.assertEqual((both["status"], both["level"]), ("declared", "confidential"))

    def test_resolve_undeclared_and_unrelated_file(self):
        self.assertEqual(self.resolve(self.undecl)["status"], "undeclared")
        # harness: キーの無い同名ファイルは無関係なものとして未宣言扱い (Fable B-5)
        self.assertEqual(self.resolve(self.unrelated)["status"], "undeclared")

    def test_resolve_unknown_reasons(self):  # AC-7
        self.assertEqual(self.resolve(self.bad)["reason"], "parse-error")
        self.assertEqual(self.resolve(self.unknownval)["reason"], "unknown-value")
        self.assertEqual(self.resolve(self.outside)["reason"], "not-a-git-repo")

    def test_wrong_type_is_unknown_not_crash(self):  # codex-review: 型違いで内部エラーにしない
        self.assertEqual(self.resolve(self.wrongtype)["reason"], "unknown-value")
        before = len(self.log_lines())
        r = self.check(self.wrongtype, "--vendor", "openai")
        self.assertIn("理由: unknown-value", r.stderr)
        self.assertEqual(len(self.log_lines()), before + 1, "判定不能も計器に残る")

    def test_worktree_reads_main_declaration(self):  # AC-8
        self.assertEqual(self.resolve(self.wt)["level"], "confidential")

    # --- egress-check (§6-2) ---
    def test_public_repo_is_silent(self):  # AC-3
        r = self.check(self.pub, "--vendor", "deepseek", "--vendor", "openai", "--vendor", "google")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_confidential_warns_but_does_not_block(self):  # AC-2
        for vendor in ("deepseek", "google", "openai"):
            r = self.check(self.conf, "--vendor", vendor)
            self.assertEqual(r.returncode, 0, "検知器は処理を止めない")
            self.assertIn("⚠ 外部送信の確認", r.stderr)
            self.assertIn("confidential", r.stderr)
        self.assertEqual(self.check(self.conf, "--vendor", "local").stderr, "", "ローカル LLM は警告しない")

    def test_internal_warns_only_deepseek(self):  # 2026-09-18 決定
        self.assertIn("DeepSeek", self.check(self.internal, "--vendor", "deepseek").stderr)
        self.assertEqual(self.check(self.internal, "--vendor", "openai").stderr, "")
        self.assertEqual(self.check(self.internal, "--vendor", "google").stderr, "")

    def test_undeclared_warns(self):
        r = self.check(self.undecl, "--vendor", "openai")
        self.assertIn("未宣言", r.stderr)
        self.assertIn("/harness-audit", r.stderr)

    def test_unknown_warns_with_reason_code(self):  # AC-7: 黙って public にしない
        for repo, reason in ((self.bad, "parse-error"), (self.unknownval, "unknown-value"), (self.outside, "not-a-git-repo")):
            r = self.check(repo, "--vendor", "openai")
            self.assertEqual(r.returncode, 0)
            self.assertIn(f"理由: {reason}", r.stderr)

    def test_target_overrides_cwd(self):  # AC-4 (事前チェック経由と環境変数経由)
        r = self.check(self.pub, "--vendor", "deepseek", "--target", str(self.conf / "README"))
        self.assertIn("confidential", r.stderr)
        r = self.check(self.pub, "--vendor", "deepseek", env_extra={"HARNESS_EGRESS_TARGETS": f"{self.conf}:{self.pub}"})
        self.assertIn("confidential", r.stderr)

    def test_cwd_is_always_included(self):  # codex-review: 機密 cwd から公開ファイルを指定しても拾う
        r = self.check(self.conf, "--vendor", "deepseek", "--target", str(self.pub / "README"))
        self.assertIn("confidential", r.stderr)

    def test_preflight_does_not_log(self):  # 事前チェックは数えない (実際の送信側で 1 回だけ)
        before = len(self.log_lines())
        r = self.check(self.conf, "--preflight", "--vendor", "deepseek")
        self.assertIn("⚠", r.stderr)
        self.assertEqual(len(self.log_lines()), before)

    def test_codex_directory_options(self):  # codex-review: -C/--cd/--add-dir で別 repo を送る経路
        for opts in (["-C", str(self.conf)], [f"--cd={self.conf}"], ["--add-dir", str(self.conf)]):
            r = self.check(self.pub, "--vendor", "openai", "--codex", "--", *opts, "exec", "x")
            self.assertIn("confidential", r.stderr, opts)
        self.assertEqual(self.check(self.pub, "--vendor", "openai", "--codex", "--", "exec", "x").stderr, "")

    def test_url_vendor_inference(self):
        self.assertIn("DeepSeek", self.check(self.conf, "--url", "https://api.deepseek.com/v1/chat/completions").stderr)
        self.assertEqual(self.check(self.conf, "--url", "https://example.com/api").stderr, "", "台帳に無い宛先は対象外")

    def test_log_is_written(self):
        before = len(self.log_lines())
        self.check(self.conf, "--vendor", "deepseek")
        after = self.log_lines()
        self.assertEqual(len(after), before + 1)
        self.assertEqual(json.loads(after[-1])["kind"], "warn")

    # --- 送信ヘルパ (curl-secret.sh) の組み込み ---
    def run_helper(self, cwd, curl_args, env_extra=None):
        fake = self.tmp / "fakebin"
        fake.mkdir(exist_ok=True)
        (fake / "curl").write_text("#!/bin/sh\necho FAKE_CURL_CALLED\n")
        (fake / "curl").chmod(0o755)
        env = dict(self.env)
        env["PATH"] = f"{fake}:{env['PATH']}"
        env.update(env_extra or {})
        script = f'. "{CURL_SECRET}"; curl_auth_bearer dummy-key {curl_args}'
        return sh(["bash", "-c", script], cwd, env)

    def test_helper_warns_before_sending_body(self):
        r = self.run_helper(self.conf, '-sf https://api.deepseek.com/v1/chat/completions \\\n -H "Content-Type: application/json" -d "{}"')
        self.assertIn("⚠ 外部送信の確認", r.stderr)
        self.assertIn("FAKE_CURL_CALLED", r.stdout, "警告しても送信は続く (止めない)")
        self.assertNotIn("⚠", r.stdout, "警告が stdout (RESPONSE の取り込み先) を汚さない")

    def test_helper_ignores_bodyless_get(self):  # AC-6: モデル存在確認・残高確認
        before = len(self.log_lines())
        r = self.run_helper(self.conf, "-sf -m 20 https://generativelanguage.googleapis.com/v1beta/models")
        self.assertNotIn("⚠", r.stderr)
        self.assertEqual(len(self.log_lines()), before, "警告ログも増えない")

    def test_helper_curl_argument_forms(self):  # codex-review: 値を取るオプション・結合表記・--url
        cases = {
            "--data= 形式": "-sf --data={} https://api.deepseek.com/v1/chat/completions",
            "--json= 形式": "-sf --json={} https://api.deepseek.com/v1/chat/completions",
            "--url= 形式": "-sf -d '{}' --url=https://api.deepseek.com/v1/chat/completions",
            "--url 値": "-sf -d '{}' --url https://api.deepseek.com/v1/chat/completions",
            "-d の値が URL": "-sf -d https://example.com https://api.deepseek.com/v1/chat/completions",
            "-d 結合表記": "-sf -d@- https://api.deepseek.com/v1/chat/completions",
        }
        for label, args in cases.items():
            self.assertIn("⚠", self.run_helper(self.conf, args).stderr, label)
        # 値を取る結合オプション (-sfm 20) の値を宛先と誤認せず、本文も無いので無音
        self.assertNotIn("⚠", self.run_helper(self.conf, "-sfm 20 https://api.deepseek.com/models").stderr)

    def test_helper_uses_targets_env(self):  # AC-4: 事前チェックを通さずヘルパを直接呼ぶ経路
        r = self.run_helper(self.pub, '-sf https://api.deepseek.com/v1/chat/completions -d "{}"',
                            env_extra={"HARNESS_EGRESS_TARGETS": str(self.conf)})
        self.assertIn("confidential", r.stderr)

    # --- 台帳・依存の欠落でも黙らない ---
    def test_ledger_unreadable_is_reported(self):
        fake_repo = self.tmp / "broken-agent-rules"
        (fake_repo / "scripts").mkdir(parents=True)
        (fake_repo / "config").mkdir()
        shutil.copy(HARNESS, fake_repo / "scripts" / "harness.py")
        (fake_repo / "config" / "egress.yml").write_text("vendors: [unclosed\n")
        r = sh([sys.executable, str(fake_repo / "scripts" / "harness.py"), "egress-check", "--vendor", "openai"], self.conf, self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("台帳", r.stderr)
        r = sh([sys.executable, str(fake_repo / "scripts" / "harness.py"), "status", "--root", str(self.root)], self.conf, self.env)
        self.assertIn("検知が働いていません", r.stdout)

    def test_without_pyyaml_still_reports(self):
        # -S で site-packages を外し PyYAML 不在を再現する。
        # 平時は無音の public repo で試す (confidential の repo だと PyYAML があっても警告が出て空振りする)
        if sh([sys.executable, "-S", "-c", "import yaml"], self.tmp, self.env).returncode == 0:
            self.skipTest("-S でも PyYAML を import できるため不在を再現できない")
        r = sh([sys.executable, "-S", str(HARNESS), "egress-check", "--vendor", "openai"], self.pub, self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("台帳", r.stderr, "PyYAML 不在で台帳を読めないことを黙らずに伝える")

    # --- status (§6-4) と audit (§6-5) ---
    def test_status_meters(self):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with open(self.log, "a") as f:
            f.write(json.dumps({"ts": old, "kind": "warn"}) + "\n")  # 7 日より前は数えない
        self.check(self.conf, "--vendor", "deepseek")
        r = sh([sys.executable, str(HARNESS), "status", "--root", str(self.root)], self.tmp, self.env)
        self.assertIn("外部送信の警告: 直近 7 日で", r.stdout)
        self.assertIn("区分が未宣言の repo:", r.stdout)

    def test_status_is_silent_when_clean(self):
        clean = self.tmp / "clean-home"
        env = dict(self.env)
        env.update({"XDG_STATE_HOME": str(clean / "state"), "XDG_CONFIG_HOME": str(clean / "config")})
        empty_root = self.tmp / "empty-root"
        empty_root.mkdir(exist_ok=True)
        r = sh([sys.executable, str(HARNESS), "status", "--root", str(empty_root)], self.tmp, env)
        self.assertEqual(r.stdout, "")

    def test_audit_propose_and_apply(self):
        env = dict(self.env)
        env["XDG_CONFIG_HOME"] = str(self.tmp / "audit-config")
        r = sh([sys.executable, str(HARNESS), "audit", "propose", "--root", str(self.root)], self.tmp, env)
        self.assertEqual(r.returncode, 0, r.stderr)
        proposal = self.tmp / "audit-config" / "agent-rules" / "harness" / "proposal.yml"
        text = proposal.read_text()
        self.assertIn("github.com/acme/plain", text)
        r = sh([sys.executable, str(HARNESS), "audit", "apply"], self.tmp, env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = sh([sys.executable, str(HARNESS), "resolve", str(self.undecl)], self.tmp, env)
        self.assertEqual(json.loads(r.stdout)["level"], "confidential", "未宣言の既定案は confidential")


if __name__ == "__main__":
    unittest.main(verbosity=2)
