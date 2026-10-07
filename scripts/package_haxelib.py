#!/usr/bin/env python3
"""Package generated Haxe classes and prebuilt desktop hdlls; consumers need no Rust/C toolchain."""
import argparse
from pathlib import Path
import zipfile
from build import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "target/hlavi.zip")
    args = parser.parse_args()
    native = sorted((ROOT / "native").glob("*/xavi.hdll"))
    if not native:
        parser.error("no built xavi.hdll; library maintainers should run scripts/build.py first")
    sources = sorted((ROOT / "haxe").rglob("*.hx"))
    if not (ROOT / "haxe/media/MediaPlayer.hx").is_file():
        parser.error("the Haxe media API has not been generated")
    examples = sorted((ROOT / "examples/player").glob("*")) + [ROOT / "examples/MediaData.hx"]
    examples = [p for p in examples if p.is_file() and p.suffix in {".hx", ".hxml", ".md"}]
    files = sources + native + examples + [ROOT / name for name in ["haxelib.json", "extraParams.hxml", "LICENSE", "README.md"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
    print(f"Packaged {len(sources)} Haxe modules and {len(native)} native platform(s): {args.output}")


if __name__ == "__main__":
    main()
