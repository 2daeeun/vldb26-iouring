"""Shared Figure 5 settings and build identity; no third-party dependencies."""

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBURING_REVISION = "4ee26f88a0592675bf623b76e116124956a048ba"
GIB = 1024**3
MIB = 1024**2

# Keep the artifact's workload semantics, including its read_ratio=0 boundary.
BASE_FLAGS = dict(
    setup_mode="defer", workload="ycsb", free_target=0.10,
    page_table_factor=2.5, ycsb_read_ratio=0, stats_interval=1_000_000,
    concurrency=128, evict_batch=128, sync_variant=False,
    posix_variant=False, submit_always=False, libaio=False,
    reg_ring=False, reg_fds=False, reg_bufs=False, nvme_cmds=False, iopoll=False,
)
CASES = [
    ("posix", "Posix Sync.", dict(concurrency=1, evict_batch=1,
                                  sync_variant=True, posix_variant=True)),
    ("uring_sync", "io_uring Sync.", dict(concurrency=1, evict_batch=1,
                                         sync_variant=True)),
    ("batch_evict", "+BatchEvict", dict(concurrency=1, sync_variant=True)),
    ("libaio_fibers", "libaio +Fibers", dict(submit_always=True, libaio=True)),
    ("uring_fibers", "io_uring +Fibers", dict(submit_always=True)),
    ("batch_submit", "+BatchSubmit", {}),
    ("regbufs", "+RegBufs", dict(reg_ring=True, reg_fds=True, reg_bufs=True)),
]
FILE_CASES = tuple(case for case, _, _ in CASES)
NVME_CASES = ("passthru", "iopoll", "sqpoll")
CASES += [
    ("passthru", "+Passthru", dict(reg_ring=True, reg_fds=True, reg_bufs=True, nvme_cmds=True)),
    ("iopoll", "+IOPoll", dict(reg_ring=True, reg_fds=True, reg_bufs=True, nvme_cmds=True, iopoll=True)),
    ("sqpoll", "+SQPoll", dict(reg_ring=True, reg_fds=True, reg_bufs=True, nvme_cmds=True,
                              iopoll=True, setup_mode="sqpoll")),
]


def command_output(argv, cwd=ROOT):
    if argv[0] == "git":
        # A raw-NVMe run may run as root from the user's explicitly selected
        # checkout. Trust only these two repositories, without global config edits.
        argv = ["git", "-c", f"safe.directory={ROOT}", "-c",
                f"safe.directory={ROOT / 'libs/liburing'}", *argv[1:]]
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_identity():
    # Includes headers and CMake files; excludes build trees and measurement data.
    paths = [ROOT / "CMakeLists.txt", ROOT / ".gitmodules"]
    paths += sorted(p for p in (ROOT / "src").rglob("*") if p.is_file())
    return {str(p.relative_to(ROOT)): sha256(p) for p in paths}


def case_flags(case_id):
    for key, _, overrides in CASES:
        if key == case_id:
            return BASE_FLAGS | overrides
    raise ValueError(f"Unknown Figure 5 case: {case_id}")


def cli_args(flags):
    args = []
    for key, value in flags.items():
        args += [f"--{key}", str(value).lower() if isinstance(value, bool) else str(value)]
    return args
