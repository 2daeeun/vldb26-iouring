"""A fixed fio comparison matrix; its metrics are IOPS, never DBMS TPS."""
import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "figure5-fio-v1"
CASES = (
    ("posix", "POSIX QD1", "psync"),
    ("uring_sync", "io_uring QD1", "io_uring"),
    ("libaio_async", "libaio QD128", "libaio"),
    ("uring_async", "io_uring QD128", "io_uring"),
    ("batch_submit", "+Submit batch", "io_uring"),
    ("regbufs", "+Registered buffers/files", "io_uring"),
    ("passthru", "+NVMe passthrough", "io_uring_cmd"),
    ("iopoll", "+IOPoll", "io_uring_cmd"),
    ("sqpoll", "+SQPoll (IOPoll on)", "io_uring_cmd"),
)
RAW_CASES = ("passthru", "iopoll", "sqpoll")
FILE_CASES = tuple(case for case, _, _ in CASES if case not in RAW_CASES)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def case_options(case, depth=128, batch=32, sq_cpu=None):
    engines = {name: engine for name, _, engine in CASES}
    if case not in engines:
        raise ValueError(f"Unknown fio case: {case}")
    qd = 1 if case in ("posix", "uring_sync") else depth
    batched = case in ("batch_submit", "regbufs", *RAW_CASES)
    options = dict(ioengine=engines[case], iodepth=qd, iodepth_low=qd,
                   iodepth_batch_submit=batch if batched else 1,
                   iodepth_batch_complete_min=1, iodepth_batch_complete_max=qd)
    if engines[case].startswith("io_uring"):
        options.update(nonvectored=1, fixedbufs=int(case in ("regbufs", *RAW_CASES)),
                       registerfiles=int(case in ("regbufs", *RAW_CASES)),
                       hipri=int(case in ("iopoll", "sqpoll")),
                       sqthread_poll=int(case == "sqpoll"), force_async=0)
    if case in RAW_CASES:
        options["cmd_type"] = "nvme"
    if case == "sqpoll":
        if sq_cpu is None:
            raise ValueError("SQPoll CPU has not been selected")
        options["sqthread_poll_cpu"] = sq_cpu
    return options


def execution_order(cases, workloads, repeats, seed, order):
    import random
    rng = random.Random(seed)
    base = list(cases)
    rng.shuffle(base)
    trials = []
    for repeat in range(1, repeats + 1):
        for workload in workloads:
            if order == "paper":
                sequence = list(cases)
            elif order == "shuffle":
                sequence = list(cases)
                rng.shuffle(sequence)
            else:
                shift = (repeat - 1) % len(base)
                sequence = base[shift:] + base[:shift]
            trials.extend(dict(case=c, workload=workload, repeat=repeat) for c in sequence)
    return trials


def parse_fio_result(path, workload, minimum_ms=0):
    data = json.loads(Path(path).read_text())
    jobs = data.get("jobs", [])
    if len(jobs) != 1 or int(jobs[0].get("error", -1)) != 0:
        raise ValueError("Expected one successful fio job; inspect fio.json and stderr.log")
    job = jobs[0]
    result = {}
    for direction in ("read", "write"):
        stats = job.get(direction, {})
        for key in ("iops", "io_bytes", "total_ios", "runtime"):
            value = float(stats.get(key, 0))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid fio {direction}.{key}")
        result[direction + "_iops"] = float(stats.get("iops", 0))
        result[direction + "_bytes"] = int(stats.get("io_bytes", 0))
        result[direction + "_ios"] = int(stats.get("total_ios", 0))
        result[direction + "_runtime_ms"] = int(stats.get("runtime", 0))
        latency = stats.get("clat_ns", {})
        percentiles = latency.get("percentile", {})
        for label, key in (("p50", "50.000000"), ("p99", "99.000000")):
            value = percentiles.get(key)
            result[f"{direction}_clat_{label}_us"] = None if value is None else float(value) / 1000
    expected = ("read", "write") if workload == "randrw" else ("write",) if workload == "prepare" else ("read",)
    for direction in expected:
        if result[direction + "_ios"] <= 0 or result[direction + "_iops"] <= 0:
            raise ValueError(f"No {direction} I/O measured")
        if result[direction + "_runtime_ms"] < minimum_ms * .9:
            raise ValueError("fio finished before the requested measurement interval")
    if workload == "randread" and result["write_ios"]:
        raise ValueError("Read-only workload unexpectedly reported writes")
    result["iops"] = result["read_iops"] + result["write_iops"]
    result["mib_per_second"] = sum(result[d + "_bytes"] * 1000 /
                                    max(1, result[d + "_runtime_ms"])
                                    for d in ("read", "write")) / 1024**2
    result["read_percent_observed"] = 100 * result["read_ios"] / (result["read_ios"] + result["write_ios"])
    result["fio_cpu_percent"] = float(job.get("usr_cpu", 0)) + float(job.get("sys_cpu", 0))
    if any(isinstance(v, float) and (not math.isfinite(v) or v < 0) for v in result.values()):
        raise ValueError("Invalid latency or CPU statistic")
    result["depth_distribution"] = job.get("iodepth_level", {})
    return result


def aggregate_rows(info, rows):
    if info.get("benchmark") != SCHEMA:
        raise ValueError("This is not a Figure 5 fio result; TPS and IOPS cannot be combined")
    output = []
    args = info["args"]
    for workload in args["workloads"]:
        for case, label, _ in CASES:
            group = [r for r in rows if r["case"] == case and r["workload"] == workload]
            passed = [r for r in group if r["status"] == "PASS"]
            repeats = [int(r["repeat"]) for r in passed]
            if len(repeats) != len(set(repeats)):
                raise ValueError(f"Duplicate successful repeat for {case}/{workload}")
            complete = (len(group) == args["repeats"] == len(passed)
                        and set(repeats) == set(range(1, args["repeats"] + 1)))
            status = "PASS" if complete else (
                "UNSUPPORTED" if args["storage"] == "file" and case in RAW_CASES else
                "NOT_SELECTED" if case not in args["cases"] else "INCOMPLETE")
            row = dict(workload=workload, case=case, label=label.replace("128", str(args["queue_depth"])),
                       status=status, successful_repeats=len(passed), expected_repeats=args["repeats"])
            for metric in ("iops", "fio_cpu_percent", "selected_cpu_cores",
                           "read_clat_p99_us", "write_clat_p99_us"):
                values = [float(r[metric]) for r in passed if r.get(metric) not in (None, "")]
                if any(not math.isfinite(v) or v < 0 for v in values):
                    raise ValueError(f"Invalid {metric} in result rows")
                good = complete and len(values) == len(passed)
                row[metric + "_median"] = statistics.median(values) if good else None
                if metric == "iops":
                    row["iops_min"] = min(values) if good else None
                    row["iops_max"] = max(values) if good else None
            output.append(row)
    return output
