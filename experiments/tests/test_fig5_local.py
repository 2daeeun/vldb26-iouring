"""Measurement validity and file lifecycle tests; run with unittest discover."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_fig5_local as runner
from fig5_common import case_flags
from plot_fig5_local import aggregate


class StatisticsTests(unittest.TestCase):
    def test_load_boundary_and_last_zero_sample(self):
        log = """ts=0 tps=0 reads=0 writes=20
ts=1 tps=50 reads=18446744073709551000 writes=18446744073709551000
ts=2 tps=100 reads=5 writes=8
ts=3 tps=0 reads=1 writes=2
"""
        result = runner.summarize_samples(runner.parse_samples(log))
        self.assertEqual(result["last_tps"], 0)
        self.assertEqual(result["mean_tps_after_first"], 50)
        self.assertEqual(result["reads_after_first"], 6)
        self.assertEqual(result["writes_after_first"], 10)

    def test_missing_measurement_or_io_does_not_become_success(self):
        for log in ("", "ts=0 tps=0 reads=5 writes=8\n",
                    "ts=0 tps=1 reads=5 writes=8\n",
                    "ts=0 tps=1 reads=0 writes=0\nts=1 tps=9 reads=0 writes=0\n"):
            with self.subTest(log=log), self.assertRaises(ValueError):
                runner.summarize_samples(runner.parse_samples(log))

    def test_malformed_statistics_are_not_evaluated(self):
        rows = runner.parse_samples("ts=1 tps=__import__('os') reads=1 writes=1\n"
                                    "ts=2 tps=-1 reads=1 writes=1\n"
                                    "[log] ts=3 tps=12 reads=1 writes=1 cq/get=-nan\n")
        self.assertEqual([row["tps"] for row in rows], ["12"])


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.output = self.base / "logs"
        self.output.mkdir()
        self.data = self.base / "data"
        self.data.mkdir()
        self.args = runner.parse_args(["--smoke"])
        self.args.file_bytes = 4096
        self.args.timeout_seconds = 2
        self.args.data_root = self.base

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, program):
        with patch.object(runner, "mount_info", return_value={}), \
             patch.object(runner, "make_command", return_value=[sys.executable, "-c", program]), \
             contextlib.redirect_stdout(io.StringIO()):
            return runner.execute_case(self.args, "posix", 1, self.output, self.data)

    def test_nonzero_exit_keeps_evidence_even_with_tps_output(self):
        row, samples = self.execute("print('ts=1 tps=22 reads=3 writes=4'); raise SystemExit(7)")
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["exit_code"], 7)
        self.assertNotIn("last_tps", row)
        self.assertEqual(len(samples), 1)
        self.assertTrue(Path(row["data_file"]).is_file())

    def test_success_removes_only_its_generated_file(self):
        sentinel = self.data / "keep.txt"
        sentinel.write_text("existing data")
        row, _ = self.execute("print('ts=1 tps=10 reads=3 writes=4'); "
                              "print('ts=2 tps=20 reads=5 writes=6')")
        self.assertEqual(row["status"], "PASS")
        self.assertFalse(Path(row["data_file"]).exists())
        self.assertEqual(sentinel.read_text(), "existing data")

    def test_existing_data_is_not_overwritten(self):
        sentinel = self.data / "r01-posix.bin"
        sentinel.write_text("existing data")
        row, _ = self.execute("raise SystemExit('must not start')")
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(sentinel.read_text(), "existing data")
        self.assertFalse((self.output / "r01-posix.log").exists())

    def test_timeout_stops_child_and_preserves_log(self):
        self.args.timeout_seconds = .1
        row, _ = self.execute("import time; print('starting', flush=True); time.sleep(60)")
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("Timeout", row["reason"])
        self.assertLess(row["elapsed_seconds"], 3)
        self.assertTrue(Path(row["data_file"]).exists())

    def test_missing_mount_and_non_directory_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "not mounted"):
            runner.mount_info(self.data, self.base / "not-a-mount")
        file = self.data / "ordinary-file"
        file.touch()
        with self.assertRaisesRegex(ValueError, "directory"):
            runner.mount_info(file, Path("/"))

    def test_mount_fallback_is_rejected(self):
        with patch.object(runner, "command_output", return_value=json.dumps({
            "filesystems": [dict(target="/unexpected", source="/dev/example", fstype="ext4", options="rw")]
        })), self.assertRaisesRegex(ValueError, "expected /"):
            runner.mount_info(self.data, Path("/"))

    def test_backend_and_registration_selection(self):
        for case_id in ("libaio_fibers", "regbufs"):
            command = runner.make_command(self.args, case_id, self.data / "new.bin")
            self.assertEqual(command[command.index("--libaio") + 1],
                             "true" if case_id == "libaio_fibers" else "false")
            binary = "buffer_mgr_libaio" if case_id == "libaio_fibers" else "buffer_mgr"
            self.assertIn(str(self.args.build_dir / binary), command)
        registered = case_flags("regbufs")
        self.assertTrue(all(registered[key] for key in ("reg_ring", "reg_fds", "reg_bufs")))
        self.assertFalse(registered["nvme_cmds"])
        self.assertFalse(registered["iopoll"])


class PlotTests(unittest.TestCase):
    def test_failed_repeat_is_missing_not_zero_or_a_partial_mean(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "run.json").write_text(json.dumps(dict(args=dict(repeats=2, cases=["posix"])) ))
            rows = [dict(case="posix", label="Posix Sync.", repeat=1, status="PASS", last_tps=100),
                    dict(case="posix", label="Posix Sync.", repeat=2, status="FAILED")]
            runner.save_csv(path / "summary.csv", rows, runner.SUMMARY_FIELDS)
            _, result = aggregate(path, "last_tps")
            self.assertEqual(result[0]["status"], "INCOMPLETE")
            self.assertEqual(result[0]["successful_repeats"], 1)
            self.assertIsNone(result[0]["median"])
            self.assertEqual(result[-1]["status"], "UNSUPPORTED")
            rows[1].update(status="PASS", last_tps=200)
            runner.save_csv(path / "summary.csv", rows, runner.SUMMARY_FIELDS)
            _, result = aggregate(path, "last_tps")
            self.assertEqual(result[0]["median"], 150)
            rows[1]["repeat"] = 1
            runner.save_csv(path / "summary.csv", rows, runner.SUMMARY_FIELDS)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                aggregate(path, "last_tps")


if __name__ == "__main__":
    unittest.main()
