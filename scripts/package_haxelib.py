#!/usr/bin/env python3
"""Package CI release assets and a small Haxelib ZIP whose macro downloads the host HDLL."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-(alpha|beta|rc)(\.(0|[1-9]\d*))?)?")


def version_of(tag):
    core, _, preview = tag.removeprefix("v").partition("-")
    if not re.fullmatch(r"\d+\.\d+\.\d+", core):
        raise ValueError(f"{tag} is not a Haxelib version")
    version = ".".join(str(int(part)) for part in core.split("."))
    if preview:
        version += "-" + preview
    if not SEMVER.fullmatch(version):
        raise ValueError(f"{tag} is not a Haxelib version")
    return version


def package(assets, tag, revision):
    manifest = json.loads((ROOT / "native/hdlls.json").read_text())
    missing = [entry["releaseAsset"] for entry in manifest["platforms"].values()
               if not (assets / entry["releaseAsset"]).is_file()]
    if missing:
        raise ValueError("missing release HDLLs: " + ", ".join(missing))
    metadata = json.loads((ROOT / "haxelib.json").read_text())
    if tag != "nightly":
        metadata["version"] = version_of(tag)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be the full hlavi commit SHA")
    manifest.update(tag=tag, revision=revision)
    for entry in manifest["platforms"].values():
        data = (assets / entry["releaseAsset"]).read_bytes()
        if not data:
            raise ValueError(f"empty release asset: {entry['releaseAsset']}")
        entry["sha256"] = hashlib.sha256(data).hexdigest()
    encoded = json.dumps(manifest, indent=2) + "\n"
    # Git/source installs can fetch this catalogue; release ZIPs carry it already.
    (assets / "hdlls.json").write_text(encoded)
    output = assets / "hlavi.zip"
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("haxelib.json", json.dumps(metadata, indent=2) + "\n")
        archive.writestr("native/hdlls.json", encoded)
        for name in ["README.md", "LICENSE", "extraParams.hxml"]:
            archive.write(ROOT / name, name)
        sources = sorted((ROOT / "haxe").rglob("*.hx"))
        sources += sorted((ROOT / "examples/player").glob("*"))
        sources += [ROOT / "examples/MediaData.hx"]
        for source in sources:
            if source.is_file() and source.suffix in {".hx", ".hxml", ".md"}:
                archive.write(source, source.relative_to(ROOT))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path, help="directory containing every CI xavi-<platform>.hdll")
    parser.add_argument("--tag", required=True, help="v<version> or nightly")
    parser.add_argument("--revision", required=True, help="hlavi commit built by CI")
    args = parser.parse_args()
    try:
        output = package(args.assets, args.tag, args.revision)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Packaged {output}; NativeInstall downloads each host's release asset")


if __name__ == "__main__":
    main()
