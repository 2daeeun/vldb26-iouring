"""PCIe qualification without device access or benchmark writes."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fig5_nvme as nvme
import run_fig5_local as runner


class PcieTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.port = Path(temp.name) / "0000:00:03.3"
        self.endpoint = self.port / "0000:07:00.0"
        self.controller = self.endpoint / "nvme/nvme0"
        self.controller.mkdir(parents=True)
        for path, maximum in ((self.port, 16), (self.endpoint, 4)):
            for field, value in dict(current_link_width=4, max_link_width=maximum,
                                     current_link_speed="8.0 GT/s PCIe", max_link_speed="8.0 GT/s PCIe",
                                     numa_node=0).items():
                (path / field).write_text(str(value))

    def test_x1_warns_and_required_x4_fails(self):
        (self.endpoint / "current_link_width").write_text("1")
        info = nvme.inspect_pcie(self.controller)
        self.assertTrue(info["warnings"])
        self.assertEqual(info["errors"], [])
        self.assertTrue(nvme.inspect_pcie(self.controller, 4)["errors"])

    def test_x4_endpoint_on_wider_port_passes_but_narrow_upstream_fails(self):
        info = nvme.inspect_pcie(self.controller, 4)
        self.assertEqual(info["errors"], [])
        self.assertEqual(info["warnings"], [])
        self.assertEqual(info["links"][0]["address"], "0000:07:00.0")
        (self.port / "current_link_width").write_text("1")
        self.assertTrue(nvme.inspect_pcie(self.controller, 4)["errors"])

    def test_unknown_width_cannot_satisfy_required_width(self):
        (self.endpoint / "current_link_width").write_text("0")
        self.assertTrue(nvme.inspect_pcie(self.controller, 4)["errors"])
        (self.endpoint / "current_link_width").unlink()
        self.assertTrue(nvme.inspect_pcie(self.controller, 4)["errors"])

    def test_width_failure_prevents_exclusive_device_open(self):
        args = runner.parse_args(["--storage", "raw-nvme", "--nvme-block", "/dev/nvme7n1",
                                  "--nvme-char", "/dev/ng7n1", "--confirm-device", "/dev/nvme7n1",
                                  "--min-pcie-width", "4"])
        (self.endpoint / "current_link_width").write_text("1")
        info = dict(errors=nvme.inspect_pcie(self.controller, 4)["errors"])
        with patch.object(nvme, "inspect_nvme", return_value=info) as inspected, \
             patch.object(nvme.os, "open") as opened:
            with self.assertRaisesRegex(ValueError, "min-pcie-width"), nvme.claim_namespace(args, {}):
                self.fail("must not acquire raw device")
            self.assertEqual(inspected.call_args.args[-1], 4)
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
