#!/usr/bin/env python3
"""Build both Figure 5 backends on the machine that will run them."""

import argparse
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fig5_common import LIBURING_REVISION, ROOT, command_output, sha256, source_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-fig5")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--arch", default="native", help="-march value; default: native")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    steps = [
        ("submodule", ["git", "-c", "submodule.liburing.url=https://github.com/axboe/liburing.git",
                       "submodule", "update", "--init", "--recursive", "--", "libs/liburing"], ROOT),
        ("liburing-configure", ["./configure", "--cc=gcc", "--cxx=g++"], ROOT / "libs/liburing"),
        ("configure", ["cmake", "-S", str(ROOT), "-B", str(build), "-G", "Unix Makefiles",
                       "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_COMPILER=gcc",
                       "-DCMAKE_CXX_COMPILER=g++", f"-DRINGDING_ARCH={args.arch}"], ROOT),
        ("compile", ["cmake", "--build", str(build), "--target", "buffer_mgr",
                     "buffer_mgr_libaio", "-j", str(args.jobs)], ROOT),
    ]
    # A failed rebuild must not leave a valid-looking identity from an older build.
    (build / "fig5-build.json").unlink(missing_ok=True)
    for name, argv, cwd in steps:
        log_path = build / f"fig5-{name}.log"
        print(f"{name}: {log_path}", flush=True)
        with log_path.open("w") as log:
            subprocess.run(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=True)
        if name == "submodule":
            revision = command_output(["git", "-C", "libs/liburing", "rev-parse", "HEAD"])
            if revision != LIBURING_REVISION:
                raise RuntimeError(f"Expected liburing {LIBURING_REVISION}, found {revision}")
            if command_output(["git", "-C", "libs/liburing", "diff", "HEAD", "--"]):
                raise RuntimeError("libs/liburing has source changes; use the pinned unmodified source")
            before = source_identity()
    after = source_identity()
    if before != after:
        raise RuntimeError("Sources changed during the build; rebuild before measuring")
    manifest = dict(
        built_at=datetime.now(timezone.utc).isoformat(), host=platform.node(),
        platform=platform.uname()._asdict(), compiler=command_output(["g++", "--version"]),
        git_head=command_output(["git", "rev-parse", "HEAD"]), liburing=revision,
        arch=args.arch, sources=after,
        binaries={name: sha256(build / name) for name in ("buffer_mgr", "buffer_mgr_libaio")},
        compile_commands_sha256=sha256(build / "compile_commands.json"),
    )
    (build / "fig5-build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built both backends: {build}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Build failed: {error}. See the fig5-*.log files in the build directory.")
