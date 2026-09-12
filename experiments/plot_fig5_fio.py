#!/usr/bin/env python3
"""Plot fio IOPS, latency and observed CPU usage without mixing in DBMS TPS."""
import argparse
import csv
import json
from pathlib import Path

from fig5_fio_common import ROOT, aggregate_rows
from run_fig5_local import save_csv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    args = parser.parse_args(argv)
    run = args.run.resolve()
    info = json.loads((run / "run.json").read_text())
    with (run / "summary.csv").open(newline="") as stream:
        rows = aggregate_rows(info, list(csv.DictReader(stream)))
    prefix = (args.output_prefix or run / "fio-comparison").resolve()
    if any(prefix.is_relative_to(ROOT / "experiments" / name) for name in ("data", "out")):
        parser.error("Choose a new output directory; do not overwrite original paper results")
    # A workload suffix also keeps graphs apart when randread is added.
    csv_path = Path(str(prefix) + ".csv")
    if csv_path == run / "summary.csv":
        parser.error("Output would overwrite raw measurement data")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for workload in info["args"]["workloads"]:
        subset = [r for r in rows if r["workload"] == workload]
        fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
        for i, row in enumerate(subset):
            if row["status"] != "PASS":
                for ax in axes:
                    ax.text(i, .02, row["status"].replace("_", "\n"), transform=ax.get_xaxis_transform(),
                            ha="center", va="bottom", fontsize=7, color="#777777")
                continue
            value = row["iops_median"] / 1000
            error = [[(row["iops_median"] - row["iops_min"]) / 1000],
                     [(row["iops_max"] - row["iops_median"]) / 1000]]
            color = "#ad8955" if row["case"] == "libaio_async" else "#487cae"
            axes[0].bar(i, value, color=color, yerr=error, capsize=4, width=.65)
            axes[0].annotate(f"{value:,.1f}", (i, row["iops_max"] / 1000),
                             xytext=(0, 5), textcoords="offset points", ha="center", fontsize=9)
            for offset, direction, color in ((-.18, "read", "#487cae"), (.18, "write", "#ad8955")):
                latency = row[direction + "_clat_p99_us_median"]
                if latency is not None:
                    axes[1].bar(i + offset, latency, width=.32, color=color,
                                label=direction if i == 0 else None)
            cores = row["selected_cpu_cores_median"]
            if cores is not None:
                axes[2].bar(i, cores, width=.65, color="#609577")
        axes[0].set_ylabel("Throughput (k IOPS)")
        axes[1].set_ylabel("Completion latency p99 (us)")
        handles, labels = axes[1].get_legend_handles_labels()
        if handles:
            axes[1].legend(handles, labels, loc="upper left")
        axes[2].set_ylabel("Observed busy CPU equivalents")
        for ax in axes:
            ax.set_ylim(bottom=0, top=max(1, ax.get_ylim()[1]) * 1.2)
            ax.grid(axis="y", color="#dddddd", linewidth=.6)
            ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
        axes[2].set_xticks(range(len(subset)), [r["label"].replace(" ", "\n", 1) for r in subset], fontsize=9)
        a = info["args"]
        mode = "SMOKE / functional check" if a["smoke"] else "I/O-path comparison"
        mix = "random read/write 50:50" if workload == "randrw" else "random read"
        fig.suptitle(f"fio / {info['preflight']['host']} / {mode} / {info['status']}\n"
                     f"{mix}; 4 KiB; {a['storage']}; {a['size_bytes'] / 1024**3:g} GiB range; "
                     f"async QD {a['queue_depth']}; submit batch {a['batch_size']}; "
                     f"{a['duration_ms'] / 1000:g}s x {a['repeats']} repeat(s)", fontsize=12)
        cpus = f"CPU {a['cpu']}" + (f" + CPU {a['sqpoll_cpu']}" if "sqpoll" in a["cases"] else "")
        fig.text(.5, .018, "Bars: medians of whole measured intervals; whiskers: min-max across repeats. "
                 "Incomplete cases have no bar.\n"
                 f"CPU: all activity on {cpus}, including startup/ramp; includes SQPoll and unrelated tasks.\n"
                 "fio has no DBMS buffer pool or fibers. IOPS is not Figure 5 TPS. One repeat does not establish variability.",
                 ha="center", fontsize=9)
        fig.tight_layout(rect=(0, .08, 1, .94))
        for extension in ("png", "pdf", "svg"):
            path = Path(f"{prefix}-{workload}.{extension}")
            fig.savefig(path, dpi=160)
            print(path)
        plt.close(fig)
    save_csv(csv_path, rows, list(rows[0]))
    print(csv_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit(f"Cannot plot Figure 5 fio experiment: {error}")
