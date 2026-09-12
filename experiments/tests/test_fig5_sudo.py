"""Exercise askpass with dummy credentials and a fake sudo; never elevate."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class AskpassTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fig5 sudo test ")
        self.root = Path(self.temp.name)
        self.password = self.root / "password.conf"
        self.helper = self.root / "sudo_askpass.sh"
        self.launcher = self.root / "sudo_exec.sh"
        self.record = self.root / "fake-sudo.json"
        self.secret = "TEST-ONLY-literal-$value-!-%s"
        self.write_password(self.secret + "\n")
        self.helper.write_text((ROOT / "sudo_askpass.sh").read_text())
        self.helper.chmod(0o755)
        fake_sudo = self.root / "fake-sudo"
        fake_sudo.write_text("""#!/usr/bin/python3
import json, os, subprocess, sys
from pathlib import Path
reply = subprocess.run([os.environ['SUDO_ASKPASS']], capture_output=True)
if reply.returncode:
    sys.stderr.buffer.write(reply.stderr)
    sys.exit(1)
matched = reply.stdout == (os.environ['TEST_EXPECTED_PASSWORD'] + '\\n').encode()
Path(os.environ['TEST_SUDO_RECORD']).write_text(json.dumps(dict(
    argv=sys.argv[1:], stdin=sys.stdin.read(), password_matched=matched)))
sys.exit(0 if matched else 1)
""")
        fake_sudo.chmod(0o755)
        code = (ROOT / "sudo_exec.sh").read_text()
        code = code.replace("SUDO=/usr/bin/sudo", "SUDO=" + shlex.quote(str(fake_sudo)))
        # Also exercise the unprivileged branch on root-only CI runners.
        code = code.replace("if (( EUID == 0 )); then", "if false; then")
        self.launcher.write_text(code)
        self.launcher.chmod(0o755)
        (self.root / "experiments").mkdir()
        for name in ("run_fig5.py", "run_fig5_local.py", "run_fig5_fio.py",
                     "plot_fig5.py", "plot_fig5_local.py", "plot_fig5_fio.py"):
            (self.root / "experiments" / name).write_text("# Never executed by fake sudo\n")
        self.env = dict(os.environ, TEST_EXPECTED_PASSWORD=self.secret, TEST_SUDO_RECORD=str(self.record))
        self.env.pop("VLDB_SUDO_ASKPASS_ACTIVE", None)
        self.env.pop("VLDB_SUDO_CALLER_UID", None)

    def tearDown(self):
        self.temp.cleanup()

    def write_password(self, text):
        self.password.write_text(text)
        self.password.chmod(0o600)

    def invoke(self, *args, env=None, input=""):
        return subprocess.run([str(self.launcher), *map(str, args)], text=True,
                              input=input, capture_output=True, env=env or self.env, timeout=5)

    def ask(self, traced=False, env=None):
        active = dict(self.env, VLDB_SUDO_ASKPASS_ACTIVE="1", VLDB_SUDO_CALLER_UID=str(os.getuid()))
        return subprocess.run((["/usr/bin/bash", "-x"] if traced else []) + [str(self.helper)],
                              text=True, capture_output=True, env=env or active, timeout=5)

    def test_direct_helper_never_discloses_password(self):
        result = self.ask(env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(self.secret, result.stderr)

    def test_literal_password_is_data_not_shell_code(self):
        marker = self.root / "must-not-exist"
        value = "$(touch " + shlex.quote(str(marker)) + ")'`$!%s"
        self.write_password(value)  # No final newline must also work.
        self.env["TEST_EXPECTED_PASSWORD"] = value
        result = self.invoke("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(result.stdout, "")
        self.assertNotIn(value, result.stderr)

    def test_comment_crlf_and_password_prefix_formats(self):
        for content in ("# explanation\r\n\r\nPASSWORD=" + self.secret + "\r\n",
                        "  # explanation\nPaSsWoRd: " + self.secret + "\n"):
            with self.subTest(format=content.splitlines()[-1].split(":")[0][:8]):
                self.write_password(content)
                result = self.invoke("--check")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(self.record.read_text())["password_matched"])

    def test_shell_trace_does_not_expose_password(self):
        result = self.ask(traced=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, self.secret + "\n")  # Captured protocol output, never printed.
        self.assertNotIn(self.secret, result.stderr)

    def test_empty_configuration_fails_without_output(self):
        for content in ("", "# enter password here\n\n", "PASSWORD=\n"):
            self.write_password(content)
            result = self.invoke("--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertFalse(self.record.exists())

    def test_missing_file_and_symlink_are_rejected(self):
        self.password.unlink()
        result = self.invoke("--check")
        self.assertNotEqual(result.returncode, 0)
        other = self.root / "other.conf"
        other.write_text(self.secret)
        other.chmod(0o600)
        self.password.symlink_to(other)
        for result in (self.invoke("--check"), self.ask()):
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_group_readable_password_is_rejected(self):
        for mode in (0o640, 0o644):
            self.password.chmod(mode)
            for result in (self.invoke("--check"), self.ask()):
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        self.assertFalse(self.record.exists())

    def test_caller_identity_mismatch_is_rejected(self):
        env = dict(self.env, VLDB_SUDO_ASKPASS_ACTIVE="1", VLDB_SUDO_CALLER_UID=str(os.getuid() + 1))
        result = self.ask(env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_runners_keep_stdin_arguments_and_memlock(self):
        for name in ("run_fig5.py", "run_fig5_local.py", "run_fig5_fio.py"):
            target = self.root / "experiments" / name
            options = ["--output-dir", str(self.root / "space in path; $(ignored)"), "--repeats", "1"]
            result = self.invoke(target, *options, input="unchanged stdin\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(self.record.read_text())
            self.assertTrue(record["password_matched"])
            self.assertEqual(record["stdin"], "unchanged stdin\n")
            self.assertEqual(record["argv"], ["-A", "-p", "", "--", "/usr/bin/prlimit",
                                            "--memlock=2147483648:2147483648", "/usr/bin/python3",
                                            str(target), *options])
            self.assertNotIn(self.secret, self.record.read_text())

    def test_plotters_use_same_authentication_without_memlock_wrapper(self):
        for name in ("plot_fig5.py", "plot_fig5_local.py", "plot_fig5_fio.py"):
            target = self.root / "experiments" / name
            result = self.invoke(target, self.root / "results")
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(self.record.read_text())
            self.assertEqual(record["argv"][4:6], ["/usr/bin/python3", str(target)])
            self.assertNotIn("/usr/bin/prlimit", record["argv"])

    def test_arbitrary_commands_and_scripts_are_rejected_before_authentication(self):
        foreign = self.root / "not-a-figure5-script.sh"
        foreign.write_text("exit 0\n")
        for target in ("/usr/bin/bash", str(foreign)):
            result = self.invoke(target)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.record.exists())

    def test_symlink_to_allowed_script_is_rejected(self):
        alias = self.root / "alias.py"
        alias.symlink_to(self.root / "experiments/run_fig5.py")
        result = self.invoke(alias)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())

    def test_check_only_authenticates_true(self):
        result = self.invoke("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(self.record.read_text())
        self.assertEqual(record["argv"], ["-A", "-p", "", "--", "/usr/bin/true"])


if __name__ == "__main__":
    unittest.main()
