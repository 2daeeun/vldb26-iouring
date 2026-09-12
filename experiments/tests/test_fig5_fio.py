"""Validity checks for method dispatch, fio failures and experiment artifacts."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fig5_fio_common as common
import run_fig5_fio as runner
import run_fig5
import plot_fig5


def sample(error=0, runtime=3000):
    stats = dict(iops=100, io_bytes=300 * 4096, total_ios=300, runtime=runtime,
                 clat_ns=dict(percentile={"50.000000": 10000, "99.000000": 20000}))
    return dict(jobs=[dict(error=error, read=dict(stats), write=dict(stats),
                           usr_cpu=10, sys_cpu=20, iodepth_level={"1": 100})])


class Results(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "fio.json"

    def tearDown(self):
        self.temp.cleanup()

    def parse(self, data, workload="randrw", duration=3000):
        self.path.write_text(json.dumps(data))
        return common.parse_fio_result(self.path, workload, duration)

    def test_job_error_rejects_even_positive_iops(self):
        with self.assertRaises(ValueError):
            self.parse(sample(error=22))

    def test_truncated_run_rejects_positive_iops(self):
        with self.assertRaises(ValueError):
            self.parse(sample(runtime=100))

    def test_nonfinite_metric_rejected(self):
        data = sample()
        data["jobs"][0]["read"]["iops"] = float("nan")
        with self.assertRaises(ValueError):
            self.parse(data)

    def test_randread_cannot_silently_include_writes(self):
        with self.assertRaises(ValueError):
            self.parse(sample(), "randread")

    def test_missing_direction_in_mixed_workload_rejected(self):
        data = sample()
        data["jobs"][0]["write"] = {}
        with self.assertRaises(ValueError):
            self.parse(data)

    def test_bandwidth_uses_measured_bytes_and_latency_units(self):
        result = self.parse(sample())
        self.assertEqual(result["iops"], 200)
        self.assertEqual(result["mib_per_second"], 200 * 4096 / 1024**2)
        self.assertEqual(result["read_clat_p99_us"], 20)

    def test_incomplete_group_does_not_plot_partial_success(self):
        info = dict(benchmark=common.SCHEMA,
                    args=dict(workloads=["randrw"], repeats=2, cases=["iopoll"], storage="raw-nvme", queue_depth=128))
        row = dict(case="iopoll", workload="randrw", repeat=1, status="PASS", iops=99)
        output = common.aggregate_rows(info, [row])
        iopoll = next(r for r in output if r["case"] == "iopoll")
        self.assertEqual(iopoll["status"], "INCOMPLETE")
        self.assertIsNone(iopoll["iops_median"])
        with self.assertRaises(ValueError):
            common.aggregate_rows(info, [row, row])

    def test_plotter_rejects_mixed_metrics(self):
        dbms, fio = self.root / "dbms", self.root / "fio"
        for path, data in ((dbms, {}), (fio, dict(benchmark=common.SCHEMA))):
            path.mkdir()
            (path / "run.json").write_text(json.dumps(data))
        self.assertEqual(plot_fig5.select([str(fio)])[0].name, "plot_fig5_fio.py")
        self.assertEqual(plot_fig5.select([str(dbms)])[0].name, "plot_fig5_local.py")
        with self.assertRaises(ValueError):
            plot_fig5.select([str(fio), str(dbms)])


class Design(unittest.TestCase):
    def test_nvme_commands_do_not_open_character_device_with_o_direct(self):
        a = runner.parse_args(["--storage", "raw-nvme", "--nvme-block", "/dev/nvme0n1",
                               "--nvme-char", "/dev/ng0n1", "--sqpoll-cpu", "25"])
        for case in ["prepare", *a.cases]:
            target = a.nvme_char if case in common.RAW_CASES else a.nvme_block
            text = runner.job_text(a, dict(case=case, workload="randrw", repeat=1), target, "/tmp/iops")
            options = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
            if options["filename"] == str(a.nvme_char):
                self.assertEqual(options["direct"], "0")
                self.assertEqual(options["ioengine"], "io_uring_cmd")
                self.assertEqual(options["cmd_type"], "nvme")
            else:
                self.assertEqual(options["direct"], "1")

    def test_installed_fio_does_not_require_a_source_build(self):
        a = runner.parse_args(["--smoke"])
        engines = subprocess.CompletedProcess([], 0, stdout="Available IO engines:\npsync\nlibaio\nio_uring\n", stderr="")
        with patch.object(runner.shutil, "which", return_value=sys.executable), \
             patch.object(runner.subprocess, "check_output", return_value="fio-3.42\n"), \
             patch.object(runner.subprocess, "run", return_value=engines), \
             patch.object(runner, "source_identity") as source:
            info = runner.validate_fio(a)
        source.assert_not_called()
        self.assertEqual(info["source"], "installed")
        self.assertEqual(info["version"], "fio-3.42")
        self.assertEqual(a.fio, str(Path(sys.executable).resolve()))

    def test_fio_missing_required_engine_fails_preflight_validation(self):
        a = runner.parse_args(["--smoke"])
        engines = subprocess.CompletedProcess([], 0, stdout="Available IO engines:\npsync\n", stderr="")
        with patch.object(runner.shutil, "which", return_value=sys.executable), \
             patch.object(runner.subprocess, "check_output", return_value="fio-3.42\n"), \
             patch.object(runner.subprocess, "run", return_value=engines), self.assertRaises(ValueError):
            runner.validate_fio(a)

    def test_method_selector_preserves_arguments_and_default(self):
        options = ["--storage", "raw-nvme", "--repeats", "1"]
        script, forwarded = run_fig5.select(["--method", "fio", *options])
        self.assertEqual(script.name, "run_fig5_fio.py")
        self.assertEqual(forwarded, options)
        self.assertEqual(run_fig5.select(options)[0].name, "run_fig5_local.py")

    def test_rng_and_range_are_constant_between_cases(self):
        a = runner.parse_args(["--smoke"])
        trial = dict(workload="randrw", repeat=1)
        jobs = [runner.job_text(a, dict(trial, case=c), "/tmp/data", "/tmp/iops") for c in common.FILE_CASES]
        for key in ("size", "offset", "bs", "randseed", "rwmixread", "runtime", "cpus_allowed"):
            self.assertEqual(len({next(line for line in job.splitlines() if line.startswith(key + "=")) for job in jobs}), 1)

    def test_sqpoll_keeps_iopoll_and_requires_second_cpu(self):
        with self.assertRaises(ValueError):
            common.case_options("sqpoll")
        options = common.case_options("sqpoll", sq_cpu=25)
        self.assertEqual((options["hipri"], options["sqthread_poll"], options["sqthread_poll_cpu"]), (1, 1, 25))

    def test_rotation_balances_positions_over_nine_repeats(self):
        cases = [c for c, _, _ in common.CASES]
        trials = common.execution_order(cases, ["randrw"], 9, 42, "rotate")
        for position in range(9):
            self.assertEqual({t["case"] for t in trials[position::9]}, set(cases))
        self.assertEqual(trials, common.execution_order(cases, ["randrw"], 9, 42, "rotate"))

    def test_rejects_ambiguous_paths_and_file_passthrough(self):
        for options in (["--data-root", "/tmp/a:b"], ["--cases", "passthru"], ["--duration-ms", "1500"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.parse_args(options)


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a = runner.parse_args(["--smoke", "--cases", "posix", "--data-root", str(self.root),
                                    "--output-dir", str(self.root / "result")])

    def tearDown(self):
        self.temp.cleanup()

    def test_nonzero_process_exit_keeps_json_but_never_passes(self):
        output = self.root / "logs"
        output.mkdir()
        original_popen = subprocess.Popen
        def fake_process(command, **kwargs):
            path = output / "randrw-r01-posix/fio.json"
            path.write_text(json.dumps(sample()))
            return original_popen([sys.executable, "-c", "raise SystemExit(7)"], **kwargs)
        with patch.object(runner.subprocess, "Popen", side_effect=fake_process):
            row = runner.execute(self.a, dict(case="posix", workload="randrw", repeat=1), output, self.root / "unused")
        self.assertEqual(row["status"], "FAILED")
        self.assertNotIn("iops", row)
        self.assertTrue((output / row["trial_dir"] / "fio.json").is_file())

    def test_preparation_failure_never_starts_measurement(self):
        keep = self.root / "existing"
        keep.write_text("preserve")
        with patch.object(runner, "execute", return_value=dict(status="FAILED", reason="test failure")) as execute, \
             contextlib.redirect_stdout(io.StringIO()):
            code = runner.run(self.a, dict(required_memlock_bytes=0))
        self.assertEqual(code, 1)
        self.assertEqual(execute.call_count, 1)
        info = json.loads((self.a.output_dir / "run.json").read_text())
        self.assertEqual(info["status"], "FAILED")
        self.assertTrue(Path(info["data_file"]).is_file())
        self.assertEqual(keep.read_text(), "preserve")

    def test_existing_output_never_overwritten(self):
        self.a.output_dir.mkdir()
        sentinel = self.a.output_dir / "run.json"
        sentinel.write_text("preserve")
        with self.assertRaises(FileExistsError):
            runner.run(self.a, dict(required_memlock_bytes=0))
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_raw_confirmation_required_before_creating_results(self):
        options = ["--storage", "raw-nvme", "--nvme-block", "/dev/nvme0n1", "--nvme-char", "/dev/ng0n1"]
        with patch.object(runner, "preflight", return_value=dict(errors=[])), patch.object(runner, "run") as run:
            with self.assertRaises(ValueError):
                runner.main(options)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
