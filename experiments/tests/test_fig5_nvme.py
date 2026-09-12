"""Raw-mode safety, Figure 5 settings, and completion semantics without raw I/O."""

import contextlib
import copy
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fig5_nvme as nvme
import run_fig5_local as runner
import plot_fig5_local as plot
from fig5_common import CASES, FILE_CASES, NVME_CASES, ROOT, case_flags


class RawSettingsTests(unittest.TestCase):
    def test_last_three_are_cumulative_and_use_character_device(self):
        args = runner.parse_args(["--storage", "raw-nvme", "--nvme-block", "/dev/nvme7n1",
                                  "--nvme-char", "/dev/ng7n1", "--sqpoll-cpu", "3"])
        self.assertEqual(len(args.cases), 10)
        for case, _, _ in CASES:
            flags = case_flags(case)
            command = runner.make_command(args, case, None)
            device = command[command.index("--ssd") + 1]
            self.assertEqual(device, "/dev/ng7n1" if case in NVME_CASES else "/dev/nvme7n1")
            if case in NVME_CASES:
                self.assertTrue(all(flags[k] for k in ("reg_ring", "reg_fds", "reg_bufs", "nvme_cmds")))
                self.assertFalse(flags["submit_always"])
                self.assertEqual((flags["concurrency"], flags["evict_batch"]), (128, 128))
                self.assertEqual(flags["iopoll"], case != "passthru")
                self.assertEqual(flags["setup_mode"], "sqpoll" if case == "sqpoll" else "defer")
            if case == "sqpoll":
                self.assertEqual(command[command.index("--sqpoll_core_id") + 1], "3")

    def test_file_mode_does_not_implicitly_enable_raw_commands(self):
        self.assertEqual(runner.parse_args([]).cases, list(FILE_CASES))
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (["--cases", "passthru"], ["--nvme-block", "/dev/nvme7n1"],
                         ["--min-pcie-width", "4"],
                         ["--storage", "raw-nvme"],
                         ["--storage", "raw-nvme", "--nvme-block", "/dev/nvme7n1",
                          "--nvme-char", "/dev/ng7n1", "--data-root", "/mnt/data"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    runner.parse_args(argv)

    def test_nvme_positive_errors_and_short_page_io_are_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "check.cpp"
            source.write_text('''#include "buffer_mgr/io_completion.hpp"
int main() {
    if (!page_io_succeeded(0, true)) return 1;
    for (int status : {1, 2, 0x80, 4096, -5}) {
        if (page_io_succeeded(status, true)) return 2;
    }
    if (!page_io_succeeded(4096, false)) return 3;
    for (int size : {0, 512, 4095, -5}) {
        if (page_io_succeeded(size, false)) return 4;
    }
}
'''.replace('#include "buffer_mgr/io_completion.hpp"',
            '#include <initializer_list>\n#include "buffer_mgr/io_completion.hpp"'))
            subprocess.run(["g++", "-std=c++23", "-I", str(ROOT / "src"), str(source),
                            "-o", str(base / "check")], check=True, capture_output=True)
            subprocess.run([str(base / "check")], check=True)


class NvmeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.sys = self.base / "sys"
        self.proc = self.base / "proc"
        self.ctrl = self.sys / "devices/nvme7"
        self.ns = self.ctrl / "nvme7n1"
        self.char = self.ctrl / "ng7n1"
        self.part = self.ns / "nvme7n1p1"
        self.char.mkdir(parents=True)
        for path in (self.ns / "holders", self.part / "holders"):
            path.mkdir(parents=True)
        files = {
            self.ctrl / "transport": "pcie", self.ctrl / "model": "test NVMe",
            self.ctrl / "serial": "test-serial", self.ctrl / "numa_node": "0",
            self.ns / "dev": "259:7", self.ns / "size": "67108864", self.ns / "nsid": "1",
            self.ns / "wwid": "test-wwid", self.ns / "diskseq": "1", self.ns / "ro": "0",
            self.ns / "metadata_bytes": "0", self.ns / "csi": "0",
            self.ns / "queue/logical_block_size": "512", self.ns / "queue/io_poll": "1",
            self.part / "dev": "259:8", self.part / "partition": "1",
            self.sys / "module/nvme/parameters/poll_queues": "1",
            self.proc / "self/mountinfo": "1 0 8:17 / / rw - ext4 /dev/sdb1 rw\n",
            self.proc / "swaps": "Filename Type Size Used Priority\n",
        }
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        for name, value in (("SYS", self.sys), ("PROC", self.proc)):
            mock = patch.object(nvme, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.identities = dict(block=dict(path="/dev/nvme7n1", dev="259:7", sysfs=str(self.ns)),
                               char=dict(path="/dev/ng7n1", dev="239:7", sysfs=str(self.char)))
        mock = patch.object(nvme, "device_identity", side_effect=lambda path, kind: self.identities[kind])
        mock.start()
        self.addCleanup(mock.stop)
        self.args = runner.parse_args(["--storage", "raw-nvme", "--nvme-block", "/dev/nvme7n1",
                                       "--nvme-char", "/dev/ng7n1", "--smoke"])

    def inspect(self, poll=True):
        return nvme.inspect_nvme(self.args.nvme_block, self.args.nvme_char, poll, self.args.file_bytes)

    def test_unused_namespace_is_identified(self):
        info = self.inspect()
        self.assertEqual(info["errors"], [])
        self.assertEqual(info["namespace_id"], 1)
        self.assertEqual(info["partitions"], ["nvme7n1p1"])

    def test_mounted_partition_is_blocked_and_mount_names_are_decoded(self):
        (self.proc / "self/mountinfo").write_text(
            "2 1 259:8 / /mnt/test\\040disk rw - ext4 /dev/nvme7n1p1 rw\n")
        info = self.inspect()
        self.assertEqual(info["mounts"][0]["target"], "/mnt/test disk")
        self.assertTrue(any("mounted" in e for e in info["errors"]))

    def test_active_swap_and_block_holders_are_blocked(self):
        with patch.object(nvme, "swaps_on", return_value=["/dev/nvme7n1p1"]):
            self.assertTrue(any("swap" in e for e in self.inspect()["errors"]))
        (self.part / "holders/dm-0").touch()
        self.assertTrue(any("held" in e for e in self.inspect()["errors"]))

    def test_swap_file_device_is_checked(self):
        swap = self.base / "swapfile"
        swap.touch()
        dev = swap.stat().st_dev
        (self.proc / "swaps").write_text(f"Filename Type Size Used Priority\n{swap} file 1024 0 -1\n")
        self.assertEqual(nvme.swaps_on({f"{os.major(dev)}:{os.minor(dev)}"}), [str(swap)])

    def test_configured_poll_parameter_alone_is_not_enough(self):
        (self.ns / "queue/io_poll").write_text("0")
        self.assertTrue(any("polling queues" in e for e in self.inspect()["errors"]))
        self.assertEqual(self.inspect(poll=False)["errors"], [])
        (self.ns / "queue/io_poll").write_text("1")
        (self.sys / "module/nvme/parameters/poll_queues").write_text("0")
        self.assertTrue(any("polling queues" in e for e in self.inspect()["errors"]))

    def test_metadata_and_read_only_namespaces_are_rejected(self):
        (self.ns / "metadata_bytes").write_text("8")
        (self.ns / "ro").write_text("1")
        errors = self.inspect()["errors"]
        self.assertTrue(any("metadata" in e for e in errors))
        self.assertTrue(any("read-only" in e for e in errors))

    def test_partition_and_wrong_character_device_are_rejected(self):
        self.identities["block"]["path"] = "/dev/nvme7n1p1"
        with self.assertRaisesRegex(ValueError, "whole NVMe namespace"):
            self.inspect()
        self.identities["block"]["path"] = "/dev/nvme7n1"
        self.identities["char"]["path"] = "/dev/ng7n2"
        with self.assertRaisesRegex(ValueError, "same NVMe namespace"):
            self.inspect()

    def test_missing_confirmation_and_device_change_do_not_open_device(self):
        info = self.inspect()
        with patch.object(nvme.os, "open") as opened:
            with self.assertRaisesRegex(ValueError, "confirm-device"), nvme.claim_namespace(self.args, info):
                self.fail("must not acquire raw device")
            self.args.confirm_device = self.args.nvme_block
            (self.ns / "diskseq").write_text("2")
            with self.assertRaisesRegex(ValueError, "changed"), nvme.claim_namespace(self.args, info):
                self.fail("must not acquire replacement device")
            opened.assert_not_called()

    def test_exclusive_claim_is_released_even_on_failure(self):
        self.args.confirm_device = self.args.nvme_block
        with patch.object(nvme.os, "open", return_value=91) as opened, \
             patch.object(nvme.os, "close") as closed, \
             patch.object(nvme, "verify_namespace_ids"):
            with self.assertRaisesRegex(RuntimeError, "stop"), nvme.claim_namespace(self.args, self.inspect()):
                flags = opened.call_args.args[1]
                self.assertTrue(flags & os.O_EXCL)
                self.assertFalse(flags & (os.O_CREAT | os.O_TRUNC))
                raise RuntimeError("stop")
            closed.assert_called_once_with(91)

    def test_ioctl_namespace_mismatch_is_rejected(self):
        with patch.object(nvme.os, "open", side_effect=[91, 92]), \
             patch.object(nvme.os, "close") as closed, \
             patch.object(nvme.fcntl, "ioctl", side_effect=[1, 2]):
            with self.assertRaisesRegex(ValueError, "namespace ID mismatch"):
                nvme.verify_namespace_ids(self.args.nvme_block, self.args.nvme_char, 1)
            self.assertEqual(closed.call_count, 2)

    def test_raw_execution_never_allocates_or_deletes_a_data_file(self):
        output = self.base / "results"
        output.mkdir()
        command = [sys.executable, "-c", "print('ts=1 tps=1 reads=1 writes=1'); print('ts=2 tps=2 reads=2 writes=2')"]
        with patch.object(runner, "make_command", return_value=command), \
             patch.object(runner, "inspect_nvme", return_value=self.inspect()), \
             patch.object(runner.os, "posix_fallocate") as allocate, \
             patch.object(Path, "unlink") as unlink, contextlib.redirect_stdout(io.StringIO()):
            row, _ = runner.execute_case(self.args, "passthru", 1, output, None, self.inspect())
            self.assertEqual(row["status"], "PASS")
            self.assertEqual(row["data_file"], "/dev/ng7n1")
            allocate.assert_not_called()
            unlink.assert_not_called()

    def test_sqpoll_avoids_worker_smt_sibling(self):
        for cpu, core in ((2, 1), (3, 1), (4, 2)):
            path = self.sys / f"devices/system/cpu/cpu{cpu}/topology"
            path.mkdir(parents=True)
            (path / "core_id").write_text(str(core))
            (path / "physical_package_id").write_text("0")
            (self.sys / f"devices/system/node/node0/cpu{cpu}").mkdir(parents=True)
        self.assertEqual(nvme.choose_sqpoll_cpu(2, 0, [2, 3, 4]), 4)
        with self.assertRaisesRegex(ValueError, "second allowed physical core"):
            nvme.choose_sqpoll_cpu(2, 0, [2, 3, 4], requested=3)


class RawPlotTests(unittest.TestCase):
    def test_raw_last_three_are_plotted_and_failures_stay_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            info = dict(storage="raw-nvme", args=dict(repeats=1, cases=list(NVME_CASES)))
            (base / "run.json").write_text(json.dumps(info))
            rows = [dict(case=case, repeat=1, status="PASS", last_tps=100) for case in NVME_CASES]
            runner.save_csv(base / "summary.csv", rows, runner.SUMMARY_FIELDS)
            _, result = plot.aggregate(base, "last_tps")
            self.assertEqual([r["status"] for r in result[-3:]], ["PASS"] * 3)
            self.assertEqual(result[0]["status"], "NOT_SELECTED")
            rows[1].update(status="FAILED", last_tps="")
            runner.save_csv(base / "summary.csv", rows, runner.SUMMARY_FIELDS)
            _, result = plot.aggregate(base, "last_tps")
            self.assertEqual(result[-2]["status"], "INCOMPLETE")
            self.assertIsNone(result[-2]["median"])

    def test_file_and_raw_runs_cannot_be_combined(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            runs = [base / "file", base / "raw-nvme"]
            for run in runs:
                run.mkdir()
                (run / "run.json").write_text(json.dumps(dict(
                    storage=run.name, mode="paper-workload", args=dict(repeats=1, cases=["posix"])) ))
                runner.save_csv(run / "summary.csv", [], runner.SUMMARY_FIELDS)
            stderr = io.StringIO()
            with patch.object(sys, "argv", ["plot", *(str(r) for r in runs), "--output-prefix", str(base / "plot")]), \
                 contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                plot.main()
            self.assertIn("different I/O paths", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
