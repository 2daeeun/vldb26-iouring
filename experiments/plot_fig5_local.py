#!/usr/bin/env python3
"""Plot new local Figure 5 measurements; preserve missing and failed cases."""

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from fig5_common import CASES, NVME_CASES, ROOT


def storage_mode(info):
    return info.get("storage", info["args"].get("storage", "file"))


def aggregate(run_dir, metric):
    info = json.loads((run_dir / "run.json").read_text())
    with (run_dir / "summary.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = int(info["args"]["repeats"])
    aggregates = []
    for case, label, _ in CASES:
        group = [row for row in rows if row["case"] == case]
        passed = [row for row in group if row["status"] == "PASS"]
        values = [float(row[metric]) for row in passed]
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError(f"Invalid {metric} in {run_dir}: {case}")
        repeats = [int(row["repeat"]) for row in passed]
        if len(set(repeats)) != len(repeats):
            raise ValueError(f"Duplicate successful repeat in {run_dir}: {case}")
        complete = (len(passed) == expected and len(group) == expected
                    and set(repeats) == set(range(1, expected + 1)))
        status = "PASS" if complete else (
            "UNSUPPORTED" if storage_mode(info) == "file" and case in NVME_CASES else
            "NOT_SELECTED" if case not in info["args"]["cases"] else "INCOMPLETE")
        # Keep incomplete cells absent from the graph; their raw values remain in summary.csv.
        aggregates.append(dict(case=case, label=label, status=status, successful_repeats=len(passed),
                               expected_repeats=expected, metric=metric,
                               median=statistics.median(values) if complete else None,
                               minimum=min(values) if complete else None,
                               maximum=max(values) if complete else None))
    return info, aggregates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="Result directories containing run.json and summary.csv")
    parser.add_argument("--metric", choices=["last", "mean"], default="last",
                        help="last: original last-sample metric; mean: supplemental mean after the first interval")
    parser.add_argument("--output-prefix", type=Path,
                        help="Output prefix; default RUN/figure5-METRIC (required for multiple runs)")
    args = parser.parse_args()
    if len(args.runs) > 1 and args.output_prefix is None:
        parser.error("Use --output-prefix for multiple runs")
    metric = "last_tps" if args.metric == "last" else "mean_tps_after_first"
    datasets = [aggregate(path.resolve(), metric) for path in args.runs]
    modes = {info["mode"] for info, _ in datasets}
    if len(modes) != 1:
        parser.error("Smoke and paper-workload runs must be plotted separately")
    if len({storage_mode(info) for info, _ in datasets}) != 1:
        parser.error("File and raw-NVMe results use different I/O paths; plot separately and rerun all ten cases on raw NVMe")
    for key in ("tuples", "pool_bytes", "duration_ms"):
        if len({info["args"][key] for info, _ in datasets}) != 1:
            parser.error(f"Run conditions differ ({key}); plot them separately")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter

    fig, axes = plt.subplots(len(datasets), 1, figsize=(13.5, 5.5 * len(datasets)), squeeze=False)
    aggregate_rows = []
    ymax = max((row["maximum"] / 1000 for _, rows in datasets for row in rows
                if row["maximum"] is not None), default=1) or 1
    for ax, (info, rows) in zip(axes[:, 0], datasets):
        ax.set_ylim(0, ymax * 1.30)
        baseline = rows[0]["median"]
        for i, row in enumerate(rows):
            if row["status"] != "PASS":
                message = "N/A\nraw NVMe" if row["status"] == "UNSUPPORTED" else (
                    "not selected" if row["status"] == "NOT_SELECTED" else
                    f"incomplete\n{row['successful_repeats']}/{row['expected_repeats']} passed")
                ax.text(i, .025, message, transform=ax.get_xaxis_transform(),
                        ha="center", va="bottom", fontsize=8, color="#666666")
            else:
                value = row["median"] / 1000
                color = "#9ab0ca" if i < 3 else "#bb9558" if i == 3 else "#487cae"
                error = [[(row["median"] - row["minimum"]) / 1000],
                         [(row["maximum"] - row["median"]) / 1000]]
                ax.bar(i, value, color=color, width=.7, yerr=error, capsize=4)
                ratio = f"\n{row['median'] / baseline:.2f}x" if baseline else ""
                ax.text(i, row["maximum"] / 1000 + ymax * .025, f"{value:,.1f}{ratio}",
                        ha="center", va="bottom", fontsize=9)
            aggregate_rows.append(dict(host=info["host"], run_id=info["run_id"], **row))
        labels = [row["label"].replace("io_uring ", "io_uring\n").replace("libaio ", "libaio\n")
                  for row in rows]
        ax.set_xticks(range(len(rows)), labels, rotation=20, ha="right")
        ax.set_xlim(-.65, len(rows) - .35)
        ax.set_ylabel("Throughput (k transactions/s)")
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#dddddd", linewidth=.6)
        ax.spines[["top", "right"]].set_visible(False)
        mode = "SMOKE - functional test only" if info["mode"] == "smoke" else "paper workload"
        args_info = info["args"]
        storage_label = "raw NVMe namespace" if storage_mode(info) == "raw-nvme" else "O_DIRECT regular file"
        links = info.get("nvme", {}).get("pcie", {}).get("links", [])
        if links:
            link = links[0]
            storage_label += f"; PCIe {link['current_link_speed']} x{link['current_link_width']}"
        sq_cpu = f"; SQPoll CPU {args_info['sqpoll_cpu']}" if args_info.get("sqpoll_cpu") is not None else ""
        ax.set_title(f"Figure 5 / {info['host']} / {mode} / {info['status']}\n"
                     f"{storage_label}; {args_info['tuples']:,} tuples; "
                     f"{args_info['pool_bytes'] / 1024**2:g} MiB pool; "
                     f"CPU {args_info['cpu']}, NUMA {args_info['numa_node']}{sq_cpu}; "
                     f"{args_info['duration_ms'] / 1000:g}s x {args_info['repeats']} repeat(s)",
                     fontsize=11, loc="left")
    metric_text = "last emitted 1-second sample" if args.metric == "last" else "mean of intervals after first nonzero sample"
    fig.text(.5, .015, f"Bars: median across repeats of {metric_text}. Whiskers: min-max.\n"
             "Ratios use this host's Posix baseline. Incomplete cases are not plotted. "
             "Artifact read_ratio=0 boundary retained.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .07 / len(datasets), 1, 1))
    prefix = args.output_prefix or args.runs[0] / f"figure5-{args.metric}"
    prefix = prefix.resolve()
    if any(prefix.is_relative_to(ROOT / "experiments" / name) for name in ("data", "out")):
        parser.error("Choose a new output directory; experiments/data and experiments/out contain original results")
    csv_path = Path(str(prefix) + ".csv")
    if any(csv_path == (run / name).resolve() for run in args.runs for name in ("summary.csv", "samples.csv")):
        parser.error("Output would overwrite raw measurement data")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf", "svg"):
        path = Path(str(prefix) + "." + extension)
        fig.savefig(path, dpi=160)
        print(path)
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(aggregate_rows[0]))
        writer.writeheader()
        writer.writerows(aggregate_rows)
    print(csv_path)
    plt.close(fig)


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit(f"Cannot plot Figure 5: {error}")
