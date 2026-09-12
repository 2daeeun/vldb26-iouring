#!/usr/bin/env python3
"""Select the original DBMS benchmark or the fio I/O-path experiment."""
import argparse
import os
import sys
from pathlib import Path


def select(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--method", choices=("dbms", "fio"), default="dbms")
    args, forwarded = parser.parse_known_args(argv)
    script = "run_fig5_local.py" if args.method == "dbms" else "run_fig5_fio.py"
    return Path(__file__).with_name(script), forwarded


if __name__ == "__main__":
    if sys.argv[1:] == ["--help"]:
        print("Usage: run_fig5.py --method {dbms,fio} [experiment options]\n"
              "Default: dbms. Use --method fio --help for fio options, "
              "or --method dbms --help for the original benchmark.")
    else:
        script, forwarded = select(sys.argv[1:])
        os.execv(sys.executable, [sys.executable, str(script), *forwarded])
