#!/usr/bin/env python3
"""Build the native adapter and stage it for the Haxe package. No extra Python packages."""
import argparse
import json
import os
import platform as host_platform
import sys
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def host_package():
    system = {"darwin": "macos", "linux": "linux", "win32": "windows"}.get(sys.platform)
    arch = host_platform.machine().lower()
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(arch, arch)
    if system is None:
        raise SystemExit(f"No native package for {sys.platform}")
    return f"{system}-{arch}"


def rust_host():
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    return next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("host: "))


def platform_for(target):
    arch = target.split("-", 1)[0]
    if "android" in target:
        return f"android-{arch}", "libhlavi.a"
    if "-ios" in target:
        simulator = "-sim" if target.endswith("-sim") or arch == "x86_64" else ""
        return f"ios-{arch}{simulator}", "libhlavi.a"
    for part, system, artifact in [
        ("-darwin", "macos", "libhlavi.dylib"),
        ("-windows-", "windows", "hlavi.dll"),
        ("-linux-", "linux", "libhlavi.so"),
    ]:
        if part in target:
            return f"{system}-{arch}", artifact
    raise SystemExit(f"No native hlavi package for {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--target", default=os.environ.get("CARGO_BUILD_TARGET"))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    target = args.target or rust_host()
    platform, artifact = platform_for(target)
    command = ["cargo", "build", "--locked", "--target", target, "--message-format=json-render-diagnostics"]
    if args.release:
        command.append("--release")
    if args.offline:
        command.append("--offline")
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True)
    built = []
    for line in result.stdout.splitlines():
        event = json.loads(line)
        if event.get("reason") == "compiler-artifact" and event["target"]["name"] == "hlavi":
            built.extend(Path(name) for name in event["filenames"] if Path(name).name == artifact)
    if len(built) != 1:
        raise SystemExit(f"Cargo did not produce exactly one {artifact}")
    destination = ROOT / "native" / platform / (artifact if artifact.endswith(".a") else "xavi.hdll")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built[0], destination)
    print(f"Built {destination}")


if __name__ == "__main__":
    main()
