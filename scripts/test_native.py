#!/usr/bin/env python3
"""Compile and run the generated media API in Ash or stock HashLink."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from build import ROOT, host_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=["ash", "hashlink"], default="ash")
    parser.add_argument("--vm", type=Path, help="Ash or HashLink executable")
    parser.add_argument("--future", type=Path, default=ROOT.parent / "ash/haxelib/ash-future", help="directory containing ash/Future.hx")
    parser.add_argument("--future-hdll", type=Path, help="stock HashLink's ash_future.hdll")
    parser.add_argument("--hdll", type=Path, help="override xavi.hdll")
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    platform = host_package()
    hdll = (args.hdll or ROOT / "native" / platform / "xavi.hdll").resolve()
    future = args.future.resolve()
    if not hdll.is_file():
        parser.error(f"no {hdll}; run python3 scripts/build.py first")
    if not (future / "ash/Future.hx").is_file():
        parser.error("--future must contain ash/Future.hx")
    vm = args.vm
    if vm is None:
        vm = ROOT.parent / "ash/target/release/ash" if args.runtime == "ash" else shutil.which("hl")
    if not args.compile_only and (vm is None or not Path(vm).is_file()):
        parser.error("no VM executable; set --vm")
    work_root = ROOT / "target/native-test"
    work_root.mkdir(parents=True, exist_ok=True)
    # Isolate concurrent runs and remove their artifacts even after failure.
    with tempfile.TemporaryDirectory(prefix=f"{args.runtime}-", dir=work_root) as temporary:
        work = Path(temporary)
        command = ["haxe", "-cp", str(ROOT / "tests"), "-cp", str(ROOT / "haxe"), "-cp", str(future),
                   "--macro", "hlavi.macro.NativeInstall.stage()", "-D", f"hlavi_hdll={hdll}",
                   "-main", "MediaTest", "-hl", str(work / "media.hl")]
        if args.runtime == "hashlink":
            command += ["-D", "ash_future_stock"]
            if not args.compile_only:
                future_hdll = args.future_hdll or future / "native" / platform / "ash_future.hdll"
                if not future_hdll.is_file():
                    parser.error("stock HashLink needs --future-hdll or a packaged ash-future installation")
                shutil.copy2(future_hdll, work / "ash_future.hdll")
        subprocess.run(command, cwd=ROOT, check=True, timeout=args.timeout)
        if not (work / "xavi.hdll").is_file():
            raise SystemExit("Haxe's NativeInstall macro did not stage xavi.hdll")
        if args.compile_only:
            print(f"COMPILE PASS ({args.runtime}); VM execution was not requested")
            return
        vm = Path(vm).resolve()
        env = os.environ.copy()
        # Stock HashLink resolves bare library names through the OS loader.
        for key in ("PATH", "DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
            env[key] = os.pathsep.join(filter(None, [str(work), str(vm.parent), env.get("HL_LIB_DIR"), env.get(key)]))
        result = subprocess.run([str(vm), "media.hl"], cwd=work, env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.timeout)
        print(result.stdout, end="")
        if result.returncode or "PASS" not in result.stdout.splitlines():
            raise SystemExit(f"{args.runtime} media test failed (exit {result.returncode})")
        print(f"NATIVE PASS ({args.runtime})")


if __name__ == "__main__":
    main()
