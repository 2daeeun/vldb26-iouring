#!/usr/bin/env python3
"""Figure 5 I/O-path comparison using fio (IOPS, not DBMS TPS)."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from build_fig5_fio import source_identity
from fig5_fio_common import (ROOT, SCHEMA, CASES, FILE_CASES, RAW_CASES, sha256,
                             case_options, execution_order, parse_fio_result)
from fig5_nvme import inspect_nvme, verify_namespace_ids, choose_sqpoll_cpu, claim_namespace
from run_fig5_local import mount_info, read_text, save_json, save_csv, stop_child

FIELDS = ["workload", "case", "repeat", "status", "reason", "iops", "read_iops",
          "write_iops", "mib_per_second", "read_percent_observed", "fio_cpu_percent",
          "selected_cpu_cores", "read_clat_p50_us", "read_clat_p99_us",
          "write_clat_p50_us", "write_clat_p99_us", "read_bytes", "write_bytes",
          "read_ios", "write_ios", "read_runtime_ms", "write_runtime_ms", "trial_dir"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--storage", choices=("file", "raw-nvme"), default="file")
    p.add_argument("--data-root", type=Path, default=Path("/mnt/nvme0n1p1"))
    p.add_argument("--expected-mount", type=Path, default=Path("/mnt/nvme0n1p1"))
    p.add_argument("--nvme-block", type=Path)
    p.add_argument("--nvme-char", type=Path)
    p.add_argument("--confirm-device", type=Path)
    p.add_argument("--min-pcie-width", type=int, choices=(1, 2, 4, 8, 16))
    p.add_argument("--cpu", type=int, default=2)
    p.add_argument("--numa-node", type=int, default=0)
    p.add_argument("--sqpoll-cpu", type=int)
    binary = p.add_mutually_exclusive_group()
    binary.add_argument("--fio", default="fio", help="Installed fio executable (default: fio in PATH)")
    binary.add_argument("--build-dir", type=Path, help="Optional repository fio build; see build_fig5_fio.py")
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--workloads", nargs="+", choices=("randrw", "randread"), default=["randrw"])
    p.add_argument("--cases", nargs="+", choices=[c for c, _, _ in CASES])
    p.add_argument("--queue-depth", type=int, default=128)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--size-bytes", type=int)
    p.add_argument("--duration-ms", type=int)
    p.add_argument("--ramp-seconds", type=int)
    p.add_argument("--repeats", type=int)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--order", choices=("rotate", "paper", "shuffle"), default="rotate")
    p.add_argument("--smoke", action="store_true")
    action = p.add_mutually_exclusive_group()
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--list-cases", action="store_true")
    a = p.parse_args(argv)
    a.cases = a.cases or ([c for c, _, _ in CASES] if a.storage == "raw-nvme" else list(FILE_CASES))
    a.size_bytes = a.size_bytes if a.size_bytes is not None else (64 * 1024**2 if a.smoke else 8 * 1024**3)
    a.duration_ms = a.duration_ms if a.duration_ms is not None else (3000 if a.smoke else 30000)
    a.ramp_seconds = a.ramp_seconds if a.ramp_seconds is not None else (0 if a.smoke else 5)
    a.repeats = a.repeats if a.repeats is not None else (1 if a.smoke else 10)
    if a.storage == "raw-nvme" and not (a.nvme_block and a.nvme_char):
        p.error("raw-nvme requires --nvme-block and --nvme-char (whole namespace)")
    if a.storage == "file" and any(c in RAW_CASES for c in a.cases):
        p.error("passthru/iopoll/sqpoll require raw-nvme; file mode supports the first six cases")
    if not 1 <= a.batch_size <= a.queue_depth <= 4096:
        p.error("Require 1 <= batch-size <= queue-depth <= 4096")
    if a.size_bytes < 64 * 1024**2 or a.size_bytes % (1024**2):
        p.error("--size-bytes must be a multiple of 1 MiB and at least 64 MiB")
    if a.duration_ms < 1000 or a.duration_ms % 1000 or a.repeats < 1 or a.ramp_seconds < 0:
        p.error("Duration must be whole seconds >= 1000 ms; repeats >= 1; ramp >= 0")
    if a.cpu < 0 or a.numa_node < 0 or a.seed < 0:
        p.error("CPU, NUMA node and seed must be nonnegative")
    if len(set(a.cases)) != len(a.cases) or len(set(a.workloads)) != len(a.workloads):
        p.error("Duplicate cases/workloads are not allowed")
    for key, value in vars(a).items():
        if isinstance(value, Path):
            if any(c in str(value) for c in ":\r\n"):
                p.error("Paths must not contain colons or newlines (fio filename syntax)")
            setattr(a, key, value.resolve())
    # Compatibility with the common, exclusive raw namespace guard.
    a.file_bytes = a.size_bytes
    return a


def validate_fio(a):
    if a.build_dir:
        info = json.loads((a.build_dir / "fig5-fio-build.json").read_text())
        if info["host"] != platform.node() or info["sources"] != source_identity():
            raise ValueError("fio build host/sources differ; rebuild with experiments/build_fig5_fio.py")
        binary = a.build_dir / "fio"
        if not os.access(binary, os.X_OK) or sha256(binary) != info["binary_sha256"]:
            raise ValueError("fio binary is missing or changed; rebuild")
        info["source"] = "repository-build"
    else:
        executable = shutil.which(a.fio)
        if executable is None:
            raise ValueError("fio executable not found; install fio or specify --fio /path/to/fio")
        binary = Path(executable).resolve()
        version = subprocess.check_output([str(binary), "--version"], text=True).strip()
        if not version.startswith("fio-"):
            raise ValueError("Expected Flexible I/O Tester (fio), not another program with the same name")
        info = dict(source="installed", version=version, binary_sha256=sha256(binary))
    info["binary"] = str(binary)
    a.fio = str(binary)
    engines = {"psync"} | {case_options(c, sq_cpu=0)["ioengine"] for c in a.cases}
    # --enghelp=psync exits 1 because psync has no private options, even when built.
    result = subprocess.run([str(binary), "--enghelp"], capture_output=True, text=True, check=True)
    available = {line.strip() for line in result.stdout.splitlines()}
    if engines - available:
        raise ValueError(f"fio engines unavailable: {sorted(engines - available)}")
    return info


def preflight(a):
    info = dict(host=platform.node(), kernel=platform.uname()._asdict(),
                kernel_cmdline=read_text("/proc/cmdline"), storage=a.storage,
                cpu=a.cpu, numa_node=a.numa_node,
                memlock=list(resource.getrlimit(resource.RLIMIT_MEMLOCK)),
                io_uring_disabled=read_text("/proc/sys/kernel/io_uring_disabled"))
    errors = []
    for program in ("numactl", "findmnt", "git"):
        if not shutil.which(program):
            errors.append(f"Missing program: {program}")
    try:
        if a.storage == "raw-nvme":
            info["nvme"] = inspect_nvme(a.nvme_block, a.nvme_char,
                                        bool({"iopoll", "sqpoll"} & set(a.cases)),
                                        a.size_bytes, a.min_pcie_width)
            errors.extend(info["nvme"]["errors"])
            info["warnings"] = info["nvme"]["warnings"]
            if os.geteuid() != 0:
                errors.append("Raw NVMe requires root: sudo prlimit --memlock=2147483648:2147483648 python3 ...")
            else:
                verify_namespace_ids(a.nvme_block, a.nvme_char, info["nvme"]["namespace_id"])
            if info["nvme"]["numa_node"] not in (None, "-1", str(a.numa_node)):
                errors.append("NVMe NUMA node differs from --numa-node; place the worker and memory near this NVMe")
        else:
            info["mount"] = mount_info(a.data_root, a.expected_mount)
            info["free_bytes"] = shutil.disk_usage(a.data_root).free
            if info["free_bytes"] < a.size_bytes + 1024**3:
                errors.append("Insufficient space for one data file plus 1 GiB reserve")
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        errors.append(str(e))
    allowed = sorted(os.sched_getaffinity(0))
    info["allowed_cpus"] = allowed
    if a.cpu not in allowed or not Path(f"/sys/devices/system/node/node{a.numa_node}/cpu{a.cpu}").exists():
        errors.append("Worker CPU is not allowed or does not belong to the requested NUMA node")
    if "sqpoll" in a.cases:
        try:
            a.sqpoll_cpu = choose_sqpoll_cpu(a.cpu, a.numa_node, allowed, a.sqpoll_cpu)
            info["sqpoll_cpu"] = a.sqpoll_cpu
        except (OSError, ValueError) as e:
            errors.append(str(e))
    info["cpu_governors"] = {str(c): read_text(f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_governor")
                             for c in {a.cpu, a.sqpoll_cpu} if c is not None}
    info["required_memlock_bytes"] = (a.queue_depth * 4096 + 16 * 1024**2
                                         if set(a.cases) & {"regbufs", *RAW_CASES} else 0)
    if info["memlock"][1] != resource.RLIM_INFINITY and info["memlock"][1] < info["required_memlock_bytes"]:
        errors.append("memlock is too small; invoke through sudo prlimit --memlock=2147483648:2147483648")
    if info["io_uring_disabled"] == "2":
        errors.append("io_uring is disabled")
    try:
        info["fio"] = validate_fio(a)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        errors.append(str(e))
    info["errors"] = errors
    return info


def job_text(a, trial, target, log_prefix):
    """One worker, one range, identical RNG seed per repeat across all cases."""
    prepare = trial["case"] == "prepare"
    # /dev/ng* rejects O_DIRECT on Linux 6.15. NVMe uring commands already
    # bypass the page cache; direct=0 here does not enable buffered file I/O.
    direct = int(trial["case"] not in RAW_CASES)
    options = dict(filename=target, size=a.size_bytes, offset=0, bs=1048576 if prepare else 4096,
                   rw="write" if prepare else trial["workload"], direct=direct, invalidate=0,
                   allow_file_create=0, numjobs=1, thread=1, group_reporting=1,
                   cpus_allowed=a.cpu, randrepeat=1, randseed=a.seed + trial["repeat"],
                   norandommap=1, random_distribution="random", refill_buffers=1)
    if prepare:
        options.update(ioengine="psync", iodepth=1, end_fsync=1)
    else:
        options.update(case_options(trial["case"], a.queue_depth, a.batch_size, a.sqpoll_cpu))
        options.update(time_based=1, runtime=a.duration_ms // 1000, ramp_time=a.ramp_seconds,
                       clat_percentiles=1, percentile_list="50:99", log_avg_msec=1000,
                       write_iops_log=log_prefix, per_job_logs=0)
        if trial["workload"] == "randrw":
            options["rwmixread"] = 50
    return "[figure5-fio]\n" + "".join(f"{k}={v}\n" for k, v in options.items())


def cpu_snapshot(cpus):
    values = {}
    for line in Path("/proc/stat").read_text().splitlines():
        fields = line.split()
        if fields[0] in {f"cpu{c}" for c in cpus}:
            ticks = list(map(int, fields[1:9]))  # Exclude guest times, already included in user/nice.
            values[fields[0]] = dict(total=sum(ticks), busy=sum(ticks) - ticks[3] - ticks[4])
    temperatures = {str(p): read_text(p) for p in Path("/sys/class/nvme").glob("*/device/hwmon/hwmon*/temp*_input")}
    return dict(cpus=values, temperatures_millidegrees=temperatures, monotonic=time.monotonic())


def cpu_cores(before, after):
    cores = 0.0
    for cpu, first in before["cpus"].items():
        last = after["cpus"][cpu]
        total = last["total"] - first["total"]
        if total <= 0:
            return None
        cores += (last["busy"] - first["busy"]) / total
    return cores


def execute(a, trial, output, target):
    directory = output / ("prepare" if trial["case"] == "prepare" else
                          f"{trial['workload']}-r{trial['repeat']:02d}-{trial['case']}")
    directory.mkdir()
    job = directory / "job.fio"
    job.write_text(job_text(a, trial, target, directory / "iops"))
    command = ["numactl", f"--cpunodebind={a.numa_node}", f"--membind={a.numa_node}",
               a.fio, "--output-format=json", f"--output={directory / 'fio.json'}", str(job)]
    save_json(directory / "command.json", command)
    cpus = {a.cpu} | ({a.sqpoll_cpu} if "sqpoll" in a.cases else set())
    before = cpu_snapshot(cpus)
    row = dict(trial, status="FAILED", reason="", trial_dir=str(directory.relative_to(output)))
    timeout = max(300, a.size_bytes // (10 * 1024**2)) if trial["case"] == "prepare" else a.duration_ms / 1000 + a.ramp_seconds + 60
    try:
        with (directory / "stdout.log").open("w") as stdout, (directory / "stderr.log").open("w") as stderr:
            child = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                code = child.wait(timeout=timeout)
            finally:
                stop_child(child)
        if code:
            raise ValueError(f"fio exited {code}; inspect {directory}")
        result = parse_fio_result(directory / "fio.json", trial["workload"],
                                  0 if trial["case"] == "prepare" else a.duration_ms)
        if trial["case"] == "prepare" and result["write_bytes"] != a.size_bytes:
            raise ValueError("fio did not initialize the entire requested range")
        save_json(directory / "metrics.json", result)
        row.update({key: value for key, value in result.items() if key in FIELDS}, status="PASS")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
        row["reason"] = str(e)
    finally:
        after = cpu_snapshot(cpus)
        save_json(directory / "host-samples.json", dict(before=before, after=after))
    row["selected_cpu_cores"] = cpu_cores(before, after)
    return row


def run(a, preflight_info):
    output = a.output_dir or ROOT / "results/figure5" / ("fio-" + platform.node() + "-" + time.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    a.output_dir = output
    trials = execution_order(a.cases, a.workloads, a.repeats, a.seed, a.order)
    info = dict(benchmark=SCHEMA, metric="IOPS", status="RUNNING", started=time.time(),
                args={k: str(v) if isinstance(v, Path) else v for k, v in vars(a).items()},
                preflight=preflight_info, trials=trials,
                runner_sources={p.name: sha256(p) for p in Path(__file__).parent.glob("*fig5*.py")})
    rows = []
    save_json(output / "run.json", info)
    print(f"Results: {output}", flush=True)
    data_dir = None
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
        required = preflight_info["required_memlock_bytes"]
        if soft != resource.RLIM_INFINITY and soft < required:
            resource.setrlimit(resource.RLIMIT_MEMLOCK, (required, hard))
        guard = claim_namespace(a, preflight_info["nvme"]) if a.storage == "raw-nvme" else nullcontext()
        with guard:
            if a.storage == "file":
                data_dir = Path(tempfile.mkdtemp(prefix="fig5-fio-", dir=a.data_root))
                target = data_dir / "data.bin"
                with target.open("xb") as stream:
                    stream.truncate(a.size_bytes)
                info["data_file"] = str(target)
                save_json(output / "run.json", info)
            else:
                target = a.nvme_block
            prepared = execute(a, dict(case="prepare", workload="prepare", repeat=0), output, target)
            info["preparation"] = prepared
            save_json(output / "run.json", info)
            if prepared["status"] != "PASS":
                raise ValueError("Range initialization failed: " + prepared["reason"])
            print("prepare: PASS", flush=True)
            for trial in trials:
                device = a.nvme_char if trial["case"] in RAW_CASES else target
                row = execute(a, trial, output, device)
                rows.append(row)
                save_csv(output / "summary.csv", rows, FIELDS)
                print(f"{trial['workload']} r{trial['repeat']:02d} {trial['case']}: {row['status']} "
                      f"{row.get('iops', 0):,.0f} IOPS {row['reason']}", flush=True)
        info["status"] = "COMPLETE" if all(r["status"] == "PASS" for r in rows) and len(rows) == len(trials) else "FAILED"
    except KeyboardInterrupt:
        info["status"] = "ABORTED"
        info["error"] = "Interrupted; child stopped before releasing the device claim"
    except (OSError, ValueError, KeyError) as e:
        info["status"], info["error"] = "FAILED", str(e)
    finally:
        info["finished"] = time.time()
        save_csv(output / "summary.csv", rows, FIELDS)
        save_json(output / "run.json", info)
        if data_dir and info["status"] == "COMPLETE":
            (data_dir / "data.bin").unlink()
            data_dir.rmdir()
    print(f"{info['status']}: {output}" + ("\n" + info["error"] if "error" in info else ""), flush=True)
    return 0 if info["status"] == "COMPLETE" else 1


def main(argv=None):
    a = parse_args(argv)
    if a.list_cases:
        for case, label, _ in CASES:
            print(f"{case:15s} {label}" + (" (raw only)" if case in RAW_CASES else ""))
        return 0
    info = preflight(a)
    if a.preflight or info["errors"]:
        display = dict(info)
        if "fio" in display and "sources" in display["fio"]:
            display["fio"] = {k: v for k, v in info["fio"].items() if k != "sources"}
            display["fio"]["source_files"] = len(info["fio"]["sources"])
        print(json.dumps(display, indent=2))
        return int(bool(info["errors"]))
    if a.dry_run:
        for case in a.cases:
            target = (a.nvme_char if case in RAW_CASES else a.nvme_block) if a.storage == "raw-nvme" else a.data_root / "<new-file>"
            print(job_text(a, dict(case=case, workload=a.workloads[0], repeat=1), target, "<trial>/iops"))
        return 0
    if a.storage == "raw-nvme" and a.confirm_device != a.nvme_block:
        raise ValueError("Raw execution writes the device. Set --confirm-device to the same whole-namespace path")
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return run(a, info)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"Cannot run Figure 5 fio experiment: {error}")
