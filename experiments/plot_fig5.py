#!/usr/bin/env python3
"""Select the plotter from run.json; keep fio IOPS and DBMS TPS separate."""
import argparse
import json
import os
from pathlib import Path
import sys

from fig5_fio_common import SCHEMA


def select(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--output-prefix", type=Path)
    p.add_argument("--metric", choices=("last", "mean"))
    a = p.parse_args(argv)
    methods = set()
    for run in a.runs:
        info = json.loads((run / "run.json").read_text())
        schema = info.get("benchmark")
        if schema not in (None, SCHEMA):
            raise ValueError(f"Unknown benchmark schema: {schema}")
        methods.add("fio" if schema == SCHEMA else "dbms")
    if len(methods) != 1:
        raise ValueError("Plot DBMS TPS and fio IOPS separately")
    if "fio" in methods and (len(a.runs) != 1 or a.metric):
        raise ValueError("fio plotting takes one result directory and has no TPS --metric")
    return Path(__file__).with_name("plot_fig5_fio.py" if "fio" in methods else "plot_fig5_local.py"), argv


if __name__ == "__main__":
    try:
        script, forwarded = select(sys.argv[1:])
        os.execv(sys.executable, [sys.executable, str(script), *forwarded])
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit(f"Cannot select Figure 5 plotter: {error}")
