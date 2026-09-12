#!/usr/bin/env python3
"""Run Figure 5 on fresh files (7 cases) or an explicitly selected raw NVMe namespace (10 cases)."""

import argparse
import csv
import fcntl
import json
import os
import platform
import random
import re
import resource
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fig5_common import (CASES, FILE_CASES, NVME_CASES, GIB, LIBURING_REVISION, MIB, ROOT,
                         case_flags, cli_args, command_output, sha256, source_identity)
from fig5_nvme import claim_namespace, choose_sqpoll_cpu, inspect_nvme, same_device, verify_namespace_ids

SUMMARY_FIELDS = ["case", "label", "repeat", "status", "reason", "last_tps",
                  "mean_tps_after_first", "measurement_samples", "reads_after_first",
                  "writes_after_first", "exit_code", "elapsed_seconds", "log", "data_file"]


def save_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def save_csv(path, rows, fields):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def mount_info(data_root, expected_mount):
    if not data_root.is_dir():
        raise ValueError(f"Data directory does not exist: {data_root}")
    if not expected_mount.is_mount():
        raise ValueError(f"Expected filesystem is not mounted: {expected_mount}")
    info = json.loads(command_output([
        "findmnt", "--json", "--target", str(data_root),
        "--output", "TARGET,SOURCE,FSTYPE,OPTIONS",
    ]))["filesystems"][0]
    if Path(info["target"]).resolve() != expected_mount:
        raise ValueError(f"Data directory is on {info['target']}, expected {expected_mount}")
    if info["fstype"] not in ("ext4", "xfs"):
        raise ValueError(f"File mode requires ext4 or xfs; found {info['fstype']}")
    if "rw" not in info["options"].split(",") or not os.access(data_root, os.W_OK):
        raise ValueError(f"Data directory is not writable: {data_root}")
    return info


def validate_build(build):
    path = build / "fig5-build.json"
    if not path.is_file():
        raise ValueError(f"Missing {path}; run python3 experiments/build_fig5.py on this host")
    info = json.loads(path.read_text())
    if info["host"] != platform.node():
        raise ValueError("Build host differs; rebuild on this machine (binaries use -march=native)")
    if info["sources"] != source_identity():
        raise ValueError("Sources have changed since the build; rerun experiments/build_fig5.py")
    for name in ("buffer_mgr", "buffer_mgr_libaio"):
        if not os.access(build / name, os.X_OK) or sha256(build / name) != info["binaries"][name]:
            raise ValueError(f"Missing or changed binary: {build / name}; rebuild")
    revision = command_output(["git", "-C", "libs/liburing", "rev-parse", "HEAD"])
    if revision != LIBURING_REVISION or revision != info["liburing"]:
        raise ValueError("liburing revision differs from the pinned build")
    if command_output(["git", "-C", "libs/liburing", "diff", "HEAD", "--"]):
        raise ValueError("liburing source has changed since the pinned build")
    return info


def preflight(args):
    errors = []
    info = dict(host=platform.node(), kernel=platform.uname()._asdict(),
                storage=args.storage,
                data_root=str(args.data_root) if args.data_root else None,
                expected_mount=str(args.expected_mount) if args.expected_mount else None,
                cpu=args.cpu, numa_node=args.numa_node,
                memlock=list(resource.getrlimit(resource.RLIMIT_MEMLOCK)),
                io_uring_disabled=read_text("/proc/sys/kernel/io_uring_disabled"))
    for program in ("numactl", "findmnt", "stdbuf", "git"):
        if not shutil.which(program):
            errors.append(f"Missing program: {program}")
    try:
        if args.storage == "file":
            info["mount"] = mount_info(args.data_root, args.expected_mount)
            info["free_bytes"] = shutil.disk_usage(args.data_root).free
            if info["free_bytes"] < args.file_bytes + GIB:
                errors.append("Not enough free space for one data file plus 1 GiB reserve")
        else:
            info["nvme"] = inspect_nvme(args.nvme_block, args.nvme_char,
                                        bool({"iopoll", "sqpoll"} & set(args.cases)), args.file_bytes,
                                        args.min_pcie_width)
            errors.extend(info["nvme"]["errors"])
            info["warnings"] = info["nvme"]["warnings"]
            info["destructive_scope"] = "Entire namespace, including partition tables and filesystem data"
            info["confirmation_matches"] = args.confirm_device == args.nvme_block
            if os.geteuid() != 0:
                errors.append("Raw NVMe runs require root; use sudo prlimit --memlock=2147483648:2147483648 python3 ...")
            else:
                verify_namespace_ids(args.nvme_block, args.nvme_char, info["nvme"]["namespace_id"])
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        errors.append(str(error))
    allowed = sorted(os.sched_getaffinity(0))
    info["allowed_cpus"] = allowed
    if args.cpu not in allowed:
        errors.append(f"CPU {args.cpu} is not in the allowed CPUs: {allowed}")
    cpu_path = Path(f"/sys/devices/system/cpu/cpu{args.cpu}")
    node_path = Path(f"/sys/devices/system/node/node{args.numa_node}")
    if not node_path.is_dir() or not (node_path / f"cpu{args.cpu}").exists():
        errors.append(f"CPU {args.cpu} does not belong to NUMA node {args.numa_node}")
    if "sqpoll" in args.cases:
        try:
            args.sqpoll_cpu = choose_sqpoll_cpu(args.cpu, args.numa_node, allowed, args.sqpoll_cpu)
            info["sqpoll_cpu"] = args.sqpoll_cpu
        except (OSError, ValueError) as error:
            errors.append(str(error))
    info["cpu_topology"] = {name: read_text(cpu_path / "topology" / name)
                            for name in ("core_id", "physical_package_id", "thread_siblings_list")}
    info["cpu_governor"] = read_text(cpu_path / "cpufreq/scaling_governor")
    info["power_online"] = {str(p): read_text(p)
                            for p in Path("/sys/class/power_supply").glob("*/online")}
    # 1 GiB registration must not silently become a smaller buffer pool.
    info["required_memlock_bytes"] = args.pool_bytes + 2 * MIB if any(case_flags(c)["reg_bufs"] for c in args.cases) else 0
    _, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    if hard != resource.RLIM_INFINITY and hard < info["required_memlock_bytes"]:
        errors.append("memlock hard limit is too small. In the invoking shell run: "
                      'sudo prlimit --pid "$$" --memlock=2147483648:2147483648')
    if info["io_uring_disabled"] == "2":
        errors.append("io_uring is disabled by the kernel setting")
    try:
        info["build"] = validate_build(args.build_dir)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        errors.append(str(error))
    info["errors"] = errors
    return info


def parse_samples(log):
    """Parse only key=value statistics; never evaluate benchmark output as code."""
    rows = []
    for line in log.splitlines():
        # Logger's multi-part output may precede an otherwise intact stats line.
        match = re.search(r"\bts=\d+\s+.*", line)
        if not match:
            continue
        row = dict(part.split("=", 1) for part in match.group().split() if "=" in part)
        try:
            for key in ("ts", "tps", "reads", "writes"):
                if int(row[key]) < 0:
                    raise ValueError(f"Negative {key}")
        except (KeyError, ValueError):
            continue
        rows.append(row)
    return rows


def summarize_samples(samples):
    first = next((i for i, row in enumerate(samples) if int(row["tps"]) > 0), None)
    # Loading has tps=0. The first nonzero interval straddles the load/txn boundary;
    # also exclude its reset/underflow-prone I/O counters from supplemental means.
    if first is None or len(samples) <= first + 1:
        raise ValueError("No complete transaction statistics interval after loading")
    measured = samples[first + 1:]
    reads = sum(int(row["reads"]) for row in measured)
    writes = sum(int(row["writes"]) for row in measured)
    if reads <= 0 or writes <= 0 or max(reads, writes) >= 2**63:
        raise ValueError("Valid read and eviction-write counters were not observed after loading")
    return dict(last_tps=int(samples[-1]["tps"]),
                mean_tps_after_first=sum(int(row["tps"]) for row in measured) / len(measured),
                measurement_samples=len(measured), reads_after_first=reads, writes_after_first=writes)


def make_command(args, case_id, data_file):
    if args.storage == "raw-nvme":
        data_file = args.nvme_char if case_id in NVME_CASES else args.nvme_block
    flags = case_flags(case_id) | dict(ssd=str(data_file), core_id=args.cpu,
                                      virt_size=args.pool_bytes, duration=args.duration_ms,
                                      ycsb_tuple_count=args.tuples)
    if case_id == "sqpoll":
        flags["sqpoll_core_id"] = args.sqpoll_cpu
    binary = "buffer_mgr_libaio" if flags["libaio"] else "buffer_mgr"
    return ["numactl", f"--cpunodebind={args.numa_node}", f"--membind={args.numa_node}",
            "stdbuf", "-oL", "-eL", str(args.build_dir / binary), *cli_args(flags)]


def stop_child(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def execute_case(args, case_id, repeat, output, data_dir, raw_info=None):
    stem = f"r{repeat:02d}-{case_id}"
    data_file = (data_dir / f"{stem}.bin" if args.storage == "file" else
                 args.nvme_char if case_id in NVME_CASES else args.nvme_block)
    log_path = output / f"{stem}.log"
    command = make_command(args, case_id, data_file)
    row = dict(case=case_id, label=dict((c, label) for c, label, _ in CASES)[case_id],
               repeat=repeat, status="FAILED", reason="", log=log_path.name,
               data_file=str(data_file))
    save_json(output / f"{stem}.command.json", command)
    print(f"[{repeat}/{args.repeats}] {case_id}: {log_path}", flush=True)
    samples = []
    started = time.monotonic()
    try:
        if args.storage == "file":
            mount_info(args.data_root, args.expected_mount)
            if shutil.disk_usage(data_dir).free < args.file_bytes + GIB:
                raise ValueError("Insufficient space (earlier failed/retained files may occupy it)")
            fd = os.open(data_file, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.posix_fallocate(fd, 0, args.file_bytes)
            finally:
                os.close(fd)
        else:
            current = inspect_nvme(args.nvme_block, args.nvme_char,
                                   case_flags(case_id)["iopoll"], args.file_bytes, args.min_pcie_width)
            if current["errors"] or raw_info is None or not same_device(current, raw_info):
                raise ValueError("Raw namespace changed or is in use: " + str(current["errors"]))
            save_json(output / f"{stem}.nvme.json", current)
        with log_path.open("x") as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            try:
                row["exit_code"] = child.wait(timeout=args.timeout_seconds)
            except subprocess.TimeoutExpired:
                row["reason"] = f"Timeout after {args.timeout_seconds}s including loading"
                stop_child(child)
                row["exit_code"] = child.returncode
            except KeyboardInterrupt:
                stop_child(child)
                raise
        samples = parse_samples(log_path.read_text(errors="replace"))
        if row["reason"]:
            pass
        elif row["exit_code"] != 0:
            row["reason"] = f"Benchmark exited with {row['exit_code']}; inspect the raw log"
        else:
            row.update(summarize_samples(samples))
            row["status"] = "PASS"
        if args.storage == "file" and row["status"] == "PASS" and not args.keep_data:
            data_file.unlink()
    except (OSError, ValueError) as error:
        row["reason"] = str(error)
    row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(f"  {row['status']}: " + (str(row.get("last_tps")) + " last-sample TPS"
                                    if row["status"] == "PASS" else row["reason"]), flush=True)
    return row, [dict(case=case_id, repeat=repeat, **sample) for sample in samples]


def run(args, info):
    needed = info["required_memlock_bytes"]
    soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    if soft != resource.RLIM_INFINITY and soft < needed:
        resource.setrlimit(resource.RLIMIT_MEMLOCK, (needed, hard))
    # Failed benchmark cores can otherwise fill the experiment disk.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    output = args.output_dir or ROOT / "results/figure5" / platform.node() / run_id
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    print(f"RESULT_DIR={output}", flush=True)
    data_dir = (Path(tempfile.mkdtemp(prefix=f"fig5-{run_id}-", dir=args.data_root))
                if args.storage == "file" else None)
    info.update(schema_version=2, run_id=run_id, status="RUNNING", started_at=datetime.now(timezone.utc).isoformat(),
                mode="smoke" if args.smoke else "paper-workload",
                io_target="regular-file-O_DIRECT" if args.storage == "file" else "raw-nvme",
                data_directory=str(data_dir) if data_dir else None, output_directory=str(output),
                args={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                effective_memlock=list(resource.getrlimit(resource.RLIMIT_MEMLOCK)),
                metric="last emitted 1-second tps sample; repeat aggregates are separate",
                workload_note="artifact read_ratio=0; original <= boundary retained (~1% reads)",
                scripts={p.name: sha256(p) for p in Path(__file__).parent.glob("*fig5*.py")})
    save_json(output / "run.json", info)
    for filename in ("fig5-build.json", "compile_commands.json", "CMakeCache.txt"):
        shutil.copy2(args.build_dir / filename, output / filename)
    (output / "source.diff").write_text(command_output(["git", "diff", "HEAD", "--", "src", "CMakeLists.txt"]))
    for command, name in [(["lscpu"], "lscpu.txt"), (["lsblk", "-J", "-o", "NAME,MODEL,SIZE,FSTYPE,MOUNTPOINTS"], "lsblk.json")]:
        if shutil.which(command[0]):
            (output / name).write_text(command_output(command) + "\n")
    trials = []
    rng = random.Random(args.seed)
    for repeat in range(1, args.repeats + 1):
        cases = list(args.cases)
        if args.order == "shuffle":
            rng.shuffle(cases)
        trials += [(case, repeat) for case in cases]
    info["execution_order"] = trials
    rows, samples = [], []
    for repeat in range(1, args.repeats + 1):
        for case, label, _ in CASES:
            if case not in args.cases:
                unsupported = args.storage == "file" and case in NVME_CASES
                rows.append(dict(case=case, label=label, repeat=repeat,
                                 status="UNSUPPORTED" if unsupported else "NOT_SELECTED",
                                 reason="Requires --storage raw-nvme" if unsupported else "Not selected by --cases"))
    save_json(output / "run.json", info)
    try:
        for case, repeat in trials:
            row, new_samples = execute_case(args, case, repeat, output, data_dir, info.get("nvme"))
            rows.append(row)
            samples.extend(new_samples)
            save_csv(output / "summary.csv", rows, SUMMARY_FIELDS)
            sample_fields = list(dict.fromkeys(key for sample in samples for key in sample))
            save_csv(output / "samples.csv", samples, sample_fields or ["case", "repeat", "ts", "tps"])
        info["status"] = "COMPLETE" if all(r["status"] != "FAILED" for r in rows) else "FAILED"
    except KeyboardInterrupt:
        rows.append(dict(case=case, repeat=repeat, status="INTERRUPTED", reason="Run interrupted"))
        info["status"] = "INTERRUPTED"
    except Exception as error:
        info["status"] = "FAILED"
        info["error"] = str(error)
        raise
    finally:
        info["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_csv(output / "summary.csv", rows, SUMMARY_FIELDS)
        save_json(output / "run.json", info)
        try:
            if data_dir:
                data_dir.rmdir()  # only if all generated data files were removed after success
        except OSError:
            pass
    print(f"{info['status']}: {output}")
    print(f"Plot: python3 experiments/plot_fig5_local.py {shlex.quote(str(output))}")
    return 0 if info["status"] == "COMPLETE" else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-fig5")
    parser.add_argument("--storage", choices=("file", "raw-nvme"), default="file")
    parser.add_argument("--nvme-block", type=Path, help="Whole unused namespace, e.g. /dev/nvme1n1; never a partition")
    parser.add_argument("--nvme-char", type=Path, help="Matching namespace character device, e.g. /dev/ng1n1")
    parser.add_argument("--confirm-device", type=Path, help="Required for raw writes: repeat the --nvme-block path; ALL DATA MAY BE LOST")
    parser.add_argument("--sqpoll-cpu", type=int, help="Second physical core on the same NUMA node; automatically selected if omitted")
    parser.add_argument("--min-pcie-width", type=int, choices=(1, 2, 4, 8, 16),
                        help="Raw mode: require this many active PCIe lanes on the SSD and upstream links (DELL: 4)")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--expected-mount", type=Path,
                        help="Refuse to run if data-root resolves to another mount")
    parser.add_argument("--output-dir", type=Path, help="New, nonexisting result directory")
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--numa-node", type=int, default=0)
    parser.add_argument("--smoke", action="store_true", help="100k tuples, 4 MiB pool; functional test only")
    parser.add_argument("--duration-ms", type=int, help="Measured duration after loading; default 10000 (smoke: 3000)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", nargs="+", choices=[c[0] for c in CASES],
                        help="Default: 7 cases for file mode, all 10 for raw-nvme")
    parser.add_argument("--order", choices=["paper", "shuffle"], default="paper")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Per-case deadline including loading")
    parser.add_argument("--keep-data", action="store_true", help="Retain successful data files too (8 GiB per trial)")
    parser.add_argument("--preflight", action="store_true", help="Check prerequisites without creating data or running I/O")
    parser.add_argument("--dry-run", action="store_true", help="Check prerequisites and print commands without writing files")
    parser.add_argument("--list-cases", action="store_true")
    args = parser.parse_args(argv)
    if args.storage == "file":
        if args.nvme_block or args.nvme_char or args.confirm_device or args.min_pcie_width is not None:
            parser.error("Device arguments require --storage raw-nvme")
        args.data_root = args.data_root or Path("/mnt/nvme0n1p1")
        args.expected_mount = args.expected_mount or Path("/mnt/nvme0n1p1")
        args.cases = args.cases or list(FILE_CASES)
        if any(c in NVME_CASES for c in args.cases):
            parser.error("Passthru/IOPoll/SQPoll require --storage raw-nvme with a dedicated namespace")
    else:
        if not args.nvme_block or not args.nvme_char:
            parser.error("raw-nvme requires both --nvme-block and --nvme-char")
        if args.data_root or args.expected_mount or args.keep_data:
            parser.error("--data-root, --expected-mount, and --keep-data apply only to file mode")
        args.cases = args.cases or [c for c, _, _ in CASES]
    args.pool_bytes = 4 * MIB if args.smoke else GIB
    args.file_bytes = 128 * MIB if args.smoke else 8 * GIB
    args.tuples = 100_000 if args.smoke else 10_000_000
    args.duration_ms = args.duration_ms if args.duration_ms is not None else (3000 if args.smoke else 10000)
    if args.duration_ms < 3000 or args.repeats < 1 or args.timeout_seconds < args.duration_ms / 1000 + 2:
        parser.error("Need duration >= 3000 ms, repeats >= 1, and a timeout allowing loading plus measurement")
    if len(set(args.cases)) != len(args.cases):
        parser.error("--cases contains duplicates")
    for key in ("build_dir", "data_root", "expected_mount", "output_dir", "nvme_block", "nvme_char", "confirm_device"):
        value = getattr(args, key)
        if value is not None:
            setattr(args, key, value.resolve())
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.list_cases:
        for case, label, _ in CASES:
            print(f"{case:16s} {label}" + (" [raw-nvme only]" if case in NVME_CASES else ""))
        return 0
    info = preflight(args)
    printable = {k: v for k, v in info.items() if k != "build"}
    print(json.dumps(printable, indent=2, ensure_ascii=False))
    if args.dry_run:
        for case in args.cases:
            placeholder = args.data_root / "NEW-RUN" / f"{case}.bin" if args.storage == "file" else None
            print(shlex.join(make_command(args, case, placeholder)))
    if info["errors"]:
        return 2
    if args.preflight or args.dry_run:
        return 0
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    if args.storage == "raw-nvme":
        with claim_namespace(args, info["nvme"]):
            return run(args, info)
    # Prevent two invocations using this data root from measuring concurrently.
    lock_fd = os.open(args.data_root / ".fig5.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another Figure 5 run holds the lock for this data root")
        return run(args, info)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Figure 5: {error}")
