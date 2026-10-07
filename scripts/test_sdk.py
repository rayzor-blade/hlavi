#!/usr/bin/env python3
"""Exercise release SDK integrity, nightly pins, and safe installation."""
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from fetch_xavi import MANIFEST, SDK, fetch, unpack, verify


class SdkTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.source = {"repository": "rayzor-blade/xavi", "tag": "nightly", "revision": "a" * 40}
        self.idl = {"repository": "rayzor-blade/x-idl", "revision": "b" * 40}
        names = ["xavi/Cargo.toml", "xavi/Cargo.lock", "xavi/api/spec/media.idl",
                 "xavi/api/media.api.rs", "x-idl/Cargo.toml", "x-idl/LICENSE"]
        names += [f"xavi/crates/{crate}/Cargo.toml" for crate in
                  ["xavi-core", "xavi-platform", "xavi-backend", "xavi-bindgen"]]
        self.files = {name: name.encode() for name in names}
        self.files["xavi/release-sources.json"] = json.dumps({"x-idl": self.idl}).encode()

    def archive(self, manifest_changes=None, extra=None, corrupt=None):
        manifest = {"schema": 1, "tag": self.source["tag"], "revision": self.source["revision"],
                    "dirty": False, "x-idl": self.idl,
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()}}
        manifest.update(manifest_changes or {})
        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(MANIFEST, json.dumps(manifest))
            for name, data in self.files.items():
                archive.writestr(name, b"corrupt" if name == corrupt else data)
            if extra:
                archive.writestr(*extra)
        data = buffer.getvalue()
        return data, hashlib.sha256(data).hexdigest()

    def test_versioned_and_nightly_download_then_verified_offline_reuse(self):
        for tag in ["nightly", "v0.1.0"]:
            self.source["tag"] = tag
            data, digest = self.archive()
            routes = {f"https://example.test/{tag}/SHA256SUMS": f"{digest}  {SDK}\n".encode(),
                      f"https://example.test/{tag}/{SDK}": data}
            destination = self.work / tag
            with patch("fetch_xavi.download", side_effect=routes.__getitem__) as download:
                installed = fetch(destination, self.source, f"https://example.test/{tag}")
                self.assertEqual(download.call_count, 2)
                self.assertEqual(installed["revision"], self.source["revision"])
                download.side_effect = AssertionError("verified installation must work offline")
                self.assertEqual(fetch(destination, self.source), installed)
            self.assertEqual(verify(destination, self.source), installed)

    def test_moved_nightly_or_dirty_sdk_is_rejected_before_installation(self):
        for changes in [{"revision": "c" * 40}, {"tag": "v9.0.0"}, {"dirty": True}]:
            data, digest = self.archive(changes)
            with self.assertRaises(ValueError):
                unpack(data, digest, self.work, self.source)
            self.assertEqual(list(self.work.iterdir()), [])

    def test_archive_and_individual_source_hashes_are_checked(self):
        data, digest = self.archive()
        with self.assertRaisesRegex(ValueError, "archive checksum"):
            unpack(data, "0" * 64, self.work, self.source)
        data, digest = self.archive(corrupt="xavi/api/spec/media.idl")
        with self.assertRaisesRegex(ValueError, "source checksum"):
            unpack(data, digest, self.work, self.source)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_traversal_symlinks_and_unlisted_entries_are_rejected(self):
        link = ZipInfo("xavi/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra in [("../escape", b"bad"), ("xavi/../../escape", b"bad"),
                      ("xavi/C:/escape", b"bad"), ("xavi\\escape", b"bad"),
                      (link, b"../../escape"), ("xavi/unlisted.rs", b"bad")]:
            data, digest = self.archive(extra=extra)
            with self.assertRaises(ValueError):
                unpack(data, digest, self.work, self.source)
            self.assertEqual(list(self.work.iterdir()), [])

    def test_existing_checkout_and_modified_installation_are_preserved(self):
        (self.work / "xavi").mkdir()
        marker = self.work / "xavi/my-work.rs"
        marker.write_text("developer changes")
        data, digest = self.archive()
        with self.assertRaisesRegex(ValueError, "refusing to replace"):
            unpack(data, digest, self.work, self.source)
        self.assertEqual(marker.read_text(), "developer changes")
        destination = self.work / "installed"
        unpack(data, digest, destination, self.source)
        changed = destination / "xavi/api/spec/media.idl"
        changed.write_text("edited")
        with patch("fetch_xavi.download", side_effect=AssertionError("must not download")):
            with self.assertRaisesRegex(ValueError, "existing sources"):
                fetch(destination, self.source)
        self.assertEqual(changed.read_text(), "edited")

    def test_missing_sdk_checksum_and_incomplete_package_fail(self):
        with patch("fetch_xavi.download", return_value=b"not a release checksum\n"):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                fetch(self.work, self.source)
        del self.files["xavi/crates/xavi-platform/Cargo.toml"]
        data, digest = self.archive()
        with self.assertRaisesRegex(ValueError, "missing required"):
            unpack(data, digest, self.work, self.source)
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
