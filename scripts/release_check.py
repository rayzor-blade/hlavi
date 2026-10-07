#!/usr/bin/env python3
"""Check the released xavi SDK pin and describe its provenance in release notes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

from fetch_xavi import source_pin, verify

ROOT = Path(__file__).resolve().parents[1]


def pins(checkouts=False, sdk=False):
    sources = json.loads((ROOT / "release-sources.json").read_text())
    source_pin(ROOT)
    for name, source in sources.items():
        if not re.fullmatch(r"[0-9a-f]{40}", source["revision"]):
            raise ValueError(f"{name} must be pinned to a full commit SHA")
    manifest = tomllib.loads((ROOT / "Cargo.toml").read_text())
    for section, crates in [("dependencies", ["xavi-core", "xavi-backend"]),
                            ("build-dependencies", ["xavi-backend", "xavi-bindgen"])]:
        for crate in crates:
            if manifest[section][crate].get("path") != f"../xavi/crates/{crate}":
                raise ValueError(f"{crate} must use the extracted xavi SDK beside hlavi")
    if sdk:
        verify(ROOT.parent, sources["xavi"])
    if checkouts:
        # Maintainer-only path; CI installs release packages without Git metadata.
        sources_with_idl = dict(sources)
        sources_with_idl.update(json.loads((ROOT.parent / "xavi/release-sources.json").read_text()))
        for name in ["xavi", "x-idl"]:
            directory = ROOT.parent / name
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=directory, text=True).strip()
            if revision != sources_with_idl[name]["revision"]:
                raise ValueError(f"{name} checkout is {revision}, expected {sources_with_idl[name]['revision']}")
            subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=directory, check=True)
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pins", "notes"])
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--checkouts", action="store_true")
    parser.add_argument("--sdk", action="store_true", help="verify the installed release SDK and every source file")
    args = parser.parse_args()
    sources = pins(args.checkouts, args.sdk)
    if args.command == "pins":
        print("Release sources: " + ", ".join(f"{name} {s['revision'][:12]}" for name, s in sources.items()))
        return
    if args.output is None:
        parser.error("notes requires an output file")
    lines = ["Native playback and media data for Haxe on Ash and HashLink.", "",
             "Install `hlavi.zip` with Haxelib. NativeInstall downloads and caches the matching desktop `xavi.hdll` on first compilation.", "",
             "Desktop assets: macOS ARM64/x86_64, Linux ARM64/x86_64, Windows x86_64. Mobile ZIPs contain static archives for host integration.", "",
             "Linux requires system GStreamer and non-FFmpeg decoder plugins. No FFmpeg fallback is included.", ""]
    for name, source in sources.items():
        lines.append(f"- [{name} {source['revision'][:12]}](https://github.com/{source['repository']}/tree/{source['revision']})")
    source = sources["xavi"]
    lines.append(f"- [xavi SDK {source['tag']}](https://github.com/{source['repository']}/releases/tag/{source['tag']}); its bundled x-idl generates the Haxe and Rust interfaces.")
    if (ROOT.parent / "xavi-sdk.json").is_file():
        manifest = verify(ROOT.parent, source)
        pin = manifest["x-idl"]
        lines.append(f"- [bundled x-idl {pin['revision'][:12]}](https://github.com/{pin['repository']}/tree/{pin['revision']})")
    idl = ROOT.parent / "xavi/api/spec/media.idl"
    if idl.is_file():
        lines += ["", f"Media IDL SHA-256: `{hashlib.sha256(idl.read_bytes()).hexdigest()}`."]
    args.output.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
