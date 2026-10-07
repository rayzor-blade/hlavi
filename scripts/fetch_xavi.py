#!/usr/bin/env python3
"""Install xavi's verified release SDK beside hlavi; never replace a developer checkout."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import urllib.request
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SDK = "xavi-sdk.zip"
MANIFEST = "xavi-sdk.json"


def source_pin(root=ROOT):
    source = json.loads((root / "release-sources.json").read_text())["xavi"]
    if source["repository"] != "rayzor-blade/xavi":
        raise ValueError("the xavi SDK must come from rayzor-blade/xavi")
    if not re.fullmatch(r"[0-9a-f]{40}", source["revision"]):
        raise ValueError("xavi must record a full source revision, including for nightly packages")
    if not re.fullmatch(r"nightly|v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", source["tag"]):
        raise ValueError("xavi tag must be nightly or a version tag")
    return source


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or (name != MANIFEST and path.parts[0] not in {"xavi", "x-idl"})):
        raise ValueError(f"unsafe SDK path: {name}")
    return path


def validate_manifest(manifest, source):
    if manifest.get("schema") != 1 or manifest.get("dirty") is not False:
        raise ValueError("SDK must be a clean schema 1 release")
    if (manifest.get("revision"), manifest.get("tag")) != (source["revision"], source["tag"]):
        raise ValueError("SDK revision/tag does not match release-sources.json; update the pin and generated Haxe together")
    pin = manifest.get("x-idl", {})
    if pin.get("repository") != "rayzor-blade/x-idl" or not re.fullmatch(r"[0-9a-f]{40}", pin.get("revision", "")):
        raise ValueError("SDK does not identify its bundled x-idl revision")
    files = manifest.get("files", {})
    required = {"xavi/Cargo.toml", "xavi/Cargo.lock", "xavi/api/spec/media.idl",
                "xavi/api/media.api.rs", "xavi/release-sources.json", "x-idl/Cargo.toml", "x-idl/LICENSE"}
    required.update(f"xavi/crates/{crate}/Cargo.toml" for crate in
                    ["xavi-core", "xavi-platform", "xavi-backend", "xavi-bindgen"])
    if not isinstance(files, dict) or not required.issubset(files):
        raise ValueError("SDK is missing required source files")
    for name, digest in files.items():
        safe_name(name)
        if name == MANIFEST or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid SDK file digest")
    return files


def verify(directory, source):
    manifest = json.loads((directory / MANIFEST).read_text())
    for name, digest in validate_manifest(manifest, source).items():
        path = directory.joinpath(*safe_name(name).parts)
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"SDK source escapes the installation: {name}")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"SDK source checksum mismatch: {name}")
    bundled = json.loads((directory / "xavi/release-sources.json").read_text())
    if bundled.get("x-idl") != manifest["x-idl"]:
        raise ValueError("bundled generator revision does not match the SDK manifest")
    return manifest


def unpack(data, digest, destination, source):
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("xavi SDK archive checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    # Validate every byte and path before creating any final source directory.
    with tempfile.TemporaryDirectory(prefix=".xavi-sdk-", dir=destination) as temporary:
        staging = Path(temporary)
        with ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("duplicate SDK archive entries")
            if sum(info.file_size for info in archive.infolist()) > 256 * 1024 * 1024:
                raise ValueError("SDK archive exceeds the 256 MiB source limit")
            for info in archive.infolist():
                safe_name(info.filename)
                mode = stat.S_IFMT(info.external_attr >> 16)
                if info.is_dir() or mode not in {0, stat.S_IFREG}:
                    raise ValueError("SDK archive contains a non-regular file")
            manifest = json.loads(archive.read(MANIFEST))
            files = validate_manifest(manifest, source)
            if set(names) != set(files) | {MANIFEST}:
                raise ValueError("SDK archive contents do not match its manifest")
            for name in names:
                path = staging.joinpath(*safe_name(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
        verify(staging, source)
        if any((destination / name).exists() for name in ["xavi", "x-idl", MANIFEST]):
            raise ValueError("refusing to replace existing xavi/x-idl sources; use an empty workspace")
        installed = []
        try:
            for name in ["xavi", "x-idl", MANIFEST]:
                path = destination / name
                (staging / name).rename(path)
                installed.append(path)
        except OSError:
            for path in installed:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            raise
    return manifest


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "hlavi-sdk-installer"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def release_assets(source):
    if source["tag"] == "nightly":
        stem = f"xavi-sdk-{source['revision']}"
        return f"{stem}.zip", f"{stem}.sha256"
    return SDK, "SHA256SUMS"


def fetch(destination, source, base_url=None):
    if any((destination / name).exists() for name in ["xavi", "x-idl", MANIFEST]):
        try:
            return verify(destination, source)
        except (OSError, ValueError) as error:
            raise ValueError("existing sources are not this SDK; use sibling checkouts for development or an empty workspace for release packages") from error
    base = base_url or f"https://github.com/{source['repository']}/releases/download/{source['tag']}"
    asset, checksum = release_assets(source)
    checksums = download(f"{base.rstrip('/')}/{checksum}").decode()
    matches = re.findall(rf"^([0-9a-f]{{64}})  {re.escape(asset)}$", checksums, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"release checksum must name exactly one {asset}")
    return unpack(download(f"{base.rstrip('/')}/{asset}"), matches[0], destination, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT.parent)
    parser.add_argument("--base-url", help="mirror containing this version's or revision's SDK ZIP and checksum")
    parser.add_argument("--archive", type=Path, help="install a downloaded SDK instead of using the network")
    parser.add_argument("--sha256", help="required checksum for --archive")
    args = parser.parse_args()
    source = source_pin()
    if args.archive:
        if not args.sha256:
            parser.error("--archive requires --sha256")
        manifest = unpack(args.archive.read_bytes(), args.sha256, args.destination, source)
    else:
        manifest = fetch(args.destination, source, args.base_url)
    print(f"Installed xavi {manifest['tag']} ({manifest['revision']}) and bundled x-idl {manifest['x-idl']['revision']}")


if __name__ == "__main__":
    main()
