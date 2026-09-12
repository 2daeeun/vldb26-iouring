#!/usr/bin/env python3
"""Build the repository's fio snapshot in a separate output directory."""
import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path

from fig5_fio_common import ROOT, sha256


def source_identity():
    result = subprocess.run(["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
                             "ls-files", "-z", "--", "fio"], check=True, capture_output=True)
    paths = sorted(filter(None, result.stdout.decode().split("\0")))
    if not paths:
        raise ValueError("The tracked fio source snapshot is missing")
    # The repository snapshot omitted Makefile (the root .gitignore ignores it).
    # Keep the exact fio-3.39 upstream Makefile under a non-ignored filename.
    paths.append("experiments/fio-v3.39.Makefile")
    return {name: sha256(ROOT / name) for name in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-fig5-fio")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    output = args.build_dir.resolve()
    if output == ROOT or output.is_relative_to(ROOT / "fio"):
        parser.error("Use a separate build directory")
    output.mkdir(parents=True, exist_ok=True)
    identity_path = output / "fig5-fio-build.json"
    identity_path.unlink(missing_ok=True)
    before = source_identity()
    source = output / "source"
    for name in before:
        target = source / ("Makefile" if name == "experiments/fio-v3.39.Makefile"
                           else Path(name).relative_to("fio"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    for step, command in (("configure", ["./configure", "--cc=gcc", "--extra-cflags=-std=gnu99"]),
                           ("compile", ["make", "-j", str(args.jobs), "fio"])):
        log = output / (step + ".log")
        print(f"{step}: {log}", flush=True)
        with log.open("w") as stream:
            subprocess.run(command, cwd=source, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if before != source_identity():
        raise ValueError("fio sources changed during the build")
    shutil.copy2(source / "fio", output / "fio")
    version = subprocess.check_output([str(output / "fio"), "--version"], text=True).strip()
    info = dict(host=platform.node(), version=version, sources=before,
                binary_sha256=sha256(output / "fio"),
                compiler=subprocess.check_output(["gcc", "--version"], text=True))
    identity_path.write_text(json.dumps(info, indent=2) + "\n")
    print(f"Built {version}: {output / 'fio'}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"fio build failed: {error}; inspect configure.log and compile.log")
