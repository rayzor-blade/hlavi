#!/usr/bin/env python3
"""Build/run the Haxe player against the local hlavi, hlwgpu and hlwindow packages."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from build import ROOT, host_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", type=Path, default=ROOT / "examples/assets/30903-383991331.mp4")
    parser.add_argument("--build", action="store_true", help="rebuild the local native libraries (library development only)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--runtime", choices=["ash", "hashlink"], default="ash")
    parser.add_argument("--vm", type=Path)
    parser.add_argument("--future", type=Path, default=ROOT.parent / "ash/haxelib/ash-future")
    parser.add_argument("--future-hdll", type=Path)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.file.is_file():
        parser.error(f"video does not exist: {args.file}")
    if args.seconds is not None and args.seconds <= 0:
        parser.error("--seconds must be positive")
    future = args.future.resolve()
    if not (future / "ash/Future.hx").is_file():
        parser.error("--future must contain ash/Future.hx")
    vm = args.vm or (ROOT.parent / "ash/target/release/ash" if args.runtime == "ash" else shutil.which("hl"))
    if vm is None or not Path(vm).is_file():
        parser.error("no runtime executable; set --vm")
    vm = Path(vm).resolve()
    if args.build:
        subprocess.run([sys.executable, str(ROOT / "scripts/build.py")] + (["--offline"] if args.offline else []), check=True)
        for package in ["hlwgpu", "hlwindow"]:
            command = ["cargo", "build", "--release", "--locked", "-p", package]
            if args.offline:
                command.append("--offline")
            subprocess.run(command, cwd=ROOT.parent / package, check=True)
    platform = host_package()
    libraries = {"xavi": ROOT / "native" / platform / "xavi.hdll"}
    for library, package in [("xgpu", "hlwgpu"), ("xwindow", "hlwindow")]:
        suffix = ".dylib" if sys.platform == "darwin" else ".dll" if sys.platform == "win32" else ".so"
        prefix = "" if sys.platform == "win32" else "lib"
        libraries[library] = ROOT.parent / package / "target/release" / f"{prefix}{package}{suffix}"
    for library, artifact in libraries.items():
        if not artifact.is_file():
            parser.error(f"no {artifact}; use --build to build the local libraries")
    work = ROOT / "target/player"
    work.mkdir(parents=True, exist_ok=True)
    for library, artifact in libraries.items():
        shutil.copy2(artifact, work / f"{library}.hdll")
    command = ["haxe", "-cp", str(ROOT / "examples/player"), "-cp", str(ROOT / "haxe"),
               "-cp", str(ROOT.parent / "hlwgpu/haxe"), "-cp", str(ROOT.parent / "hlwindow/haxe"),
               "-cp", str(future), "-main", "VideoPlayer", "-hl", str(work / "player.hl")]
    if args.runtime == "hashlink":
        command += ["-D", "ash_future_stock"]
        extension = args.future_hdll or future / "native" / platform / "ash_future.hdll"
        if not extension.is_file():
            parser.error("HashLink requires --future-hdll or a packaged ash-future installation")
        shutil.copy2(extension, work / "ash_future.hdll")
    subprocess.run(command, check=True)
    command = [str(vm), "player.hl", str(args.file.resolve())]
    if args.seconds is not None:
        command += ["--seconds", str(args.seconds)]
    if args.capture:
        command += ["--capture", str(args.capture.resolve())]
    if args.self_test:
        command.append("--self-test")
    env = os.environ.copy()
    for key in ("PATH", "DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        env[key] = os.pathsep.join(filter(None, [str(work), str(vm.parent), env.get("HL_LIB_DIR"), env.get(key)]))
    timeout = 60 if args.self_test else args.seconds + 60 if args.seconds else None
    subprocess.run(command, cwd=work, env=env, check=True, timeout=timeout)


if __name__ == "__main__":
    main()
