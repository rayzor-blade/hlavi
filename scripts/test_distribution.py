#!/usr/bin/env python3
"""Exercise release packaging and the real Haxe installer without Rust or a VM."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from zipfile import ZipFile

from build import host_package
from package_haxelib import ROOT, package, version_of


class PackageTest(unittest.TestCase):
    def test_release_catalogue_and_haxelib(self):
        original = (ROOT / "native/hdlls.json").read_bytes()
        catalogue = json.loads(original)
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            for platform, entry in catalogue["platforms"].items():
                (assets / entry["releaseAsset"]).write_bytes(platform.encode())
            output = package(assets, "v2026.10.07", "a" * 40)
            with ZipFile(output) as archive:
                manifest = json.loads(archive.read("native/hdlls.json"))
                self.assertEqual(manifest, json.loads((assets / "hdlls.json").read_text()))
                self.assertEqual(manifest["tag"], "v2026.10.07")
                self.assertEqual(manifest["revision"], "a" * 40)
                self.assertEqual(json.loads(archive.read("haxelib.json"))["version"], "2026.10.7")
                for platform, entry in manifest["platforms"].items():
                    self.assertEqual(entry["sha256"], hashlib.sha256(platform.encode()).hexdigest())
                self.assertIn("haxe/media/MediaPlayer.hx", archive.namelist())
                self.assertIn("haxe/hlavi/macro/NativeInstall.hx", archive.namelist())
                self.assertIn("extraParams.hxml", archive.namelist())
                self.assertFalse(any(name.endswith((".hdll", ".rs", ".c", ".mp4")) for name in archive.namelist()))
            with ZipFile(package(assets, "nightly", "b" * 40)) as archive:
                self.assertEqual(json.loads(archive.read("haxelib.json"))["version"],
                                 json.loads((ROOT / "haxelib.json").read_text())["version"])
        self.assertEqual((ROOT / "native/hdlls.json").read_bytes(), original)

    def test_incomplete_release_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            with self.assertRaisesRegex(ValueError, "missing release HDLLs"):
                package(assets, "v0.1.0", "a" * 40)
            self.assertFalse((assets / "hlavi.zip").exists())

    def test_versions(self):
        self.assertEqual(version_of("v1.2.3-rc.1"), "1.2.3-rc.1")
        for tag in ["main", "v1.2", "v1.2.3/evil", "v1.2.3-beta.01"]:
            with self.assertRaises(ValueError):
                version_of(tag)


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.root = self.work / "package"
        self.cache = self.work / "cache"
        self.output = self.work / "output"
        self.output.mkdir()
        self.hdll = self.output / "xavi.hdll"
        self.binary = b"fixture native library\x00\xff\x00"
        self.platform = host_package()
        self.asset = f"xavi-{self.platform}.hdll"
        self.digest = hashlib.sha256(self.binary).hexdigest()
        self.manifest = {"repository": "rayzor-blade/hlavi", "tag": "v0.1.0", "platforms": {
            self.platform: {"releaseAsset": self.asset, "packagePath": f"native/{self.platform}/xavi.hdll",
                            "sha256": self.digest}}}
        macro = self.root / "haxe/hlavi/macro/NativeInstall.hx"
        macro.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "haxe/hlavi/macro/NativeInstall.hx", macro)
        (self.root / "native").mkdir()
        self.write_manifest()
        (self.work / "Main.hx").write_text("class Main { static function main() {} }\n")
        self.requests = []
        self.routes = {f"/release/{self.asset}": (200, {}, self.binary)}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                status, headers, body = owner.routes.get(self.path, (404, {}, b"not found"))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}/release"

    def write_manifest(self):
        (self.root / "native/hdlls.json").write_text(json.dumps(self.manifest))

    def compile(self, *defines, success=True, target="hl"):
        extension = {"hl": "hl", "js": "js", "hlc": "c"}[target]
        flag = "hl" if target == "hlc" else target
        command = ["haxe", "-cp", str(self.root / "haxe"), "-cp", str(self.work), "-main", "Main",
                   f"-{flag}", str(self.output / f"main.{extension}"), "--macro", "hlavi.macro.NativeInstall.stage()",
                   "-D", f"hlavi_cache={self.cache}", "-D", f"hlavi_release_url={self.base}"]
        for define in defines:
            command += ["-D", define]
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def cached(self):
        return self.cache / "v0.1.0" / self.platform / self.digest / "xavi.hdll"

    def test_download_redirect_cache_and_offline(self):
        self.routes[f"/release/{self.asset}"] = (302, {"Location": "/binary"}, b"")
        self.routes["/binary"] = (200, {}, self.binary)
        self.compile()
        self.assertEqual(self.hdll.read_bytes(), self.binary)
        self.assertEqual(self.cached().read_bytes(), self.binary)
        self.assertEqual(self.requests, [f"/release/{self.asset}", "/binary"])
        self.hdll.unlink()
        self.routes.clear()
        self.compile("hlavi_offline")
        self.assertEqual(self.hdll.read_bytes(), self.binary)
        self.assertEqual(len(self.requests), 2)

    def test_corrupt_cache_is_replaced(self):
        self.cached().parent.mkdir(parents=True)
        self.cached().write_bytes(b"corrupt")
        self.compile()
        self.assertEqual(self.cached().read_bytes(), self.binary)
        self.assertEqual(self.hdll.read_bytes(), self.binary)

    def test_checksum_mismatch_never_stages_or_caches(self):
        self.routes[f"/release/{self.asset}"] = (200, {}, b"wrong release")
        self.assertIn("does not match", self.compile(success=False))
        self.assertFalse(self.hdll.exists())
        self.assertFalse(self.cached().exists())
        self.assertEqual(list(self.cache.rglob("*.tmp")), [])

    def test_missing_asset_and_offline_fail_clearly(self):
        self.assertIn("hlavi_offline", self.compile("hlavi_offline", success=False))
        self.assertEqual(self.requests, [])
        self.routes.clear()
        self.assertIn("check that the release is published", self.compile(success=False))
        self.assertFalse(self.hdll.exists())

    def test_local_build_and_explicit_override(self):
        local = self.root / self.manifest["platforms"][self.platform]["packagePath"]
        local.parent.mkdir(parents=True)
        local.write_bytes(self.binary)
        self.compile("hlavi_offline")
        self.assertEqual(self.requests, [])
        local.write_bytes(b"bad bundled release")
        self.assertIn("Checksum mismatch", self.compile(success=False))
        explicit = self.work / "developer.hdll"
        explicit.write_bytes(b"developer build")
        self.compile(f"hlavi_hdll={explicit}", "hlavi_offline")
        self.assertEqual(self.hdll.read_bytes(), b"developer build")
        self.assertEqual(self.requests, [])

    def test_source_install_fetches_and_caches_release_manifest(self):
        self.routes["/release/hdlls.json"] = (200, {}, json.dumps(self.manifest).encode())
        del self.manifest["platforms"][self.platform]["sha256"]
        self.write_manifest()
        self.compile()
        self.assertEqual(self.requests, ["/release/hdlls.json", f"/release/{self.asset}"])
        self.hdll.unlink()
        self.compile("hlavi_offline")
        self.assertEqual(self.hdll.read_bytes(), self.binary)
        self.assertEqual(len(self.requests), 2)

    def test_mismatched_remote_manifest_is_rejected(self):
        remote = dict(self.manifest, tag="v9.0.0")
        self.routes["/release/hdlls.json"] = (200, {}, json.dumps(remote).encode())
        del self.manifest["platforms"][self.platform]["sha256"]
        self.write_manifest()
        self.assertIn("manifest does not match", self.compile(success=False))
        self.assertEqual(self.requests, ["/release/hdlls.json"])
        self.assertFalse((self.cache / "v0.1.0/hdlls.json").exists())

    def test_invalid_remote_hash_is_not_cached(self):
        self.manifest["platforms"][self.platform]["sha256"] = "not-a-checksum"
        self.routes["/release/hdlls.json"] = (200, {}, json.dumps(self.manifest).encode())
        del self.manifest["platforms"][self.platform]["sha256"]
        self.write_manifest()
        self.assertIn("manifest does not match", self.compile(success=False))
        self.assertFalse((self.cache / "v0.1.0/hdlls.json").exists())

    def test_skip_native_for_embedding_hlc_and_non_hl(self):
        self.compile("hlavi_no_hdll")
        self.compile(target="hlc")
        self.compile(target="js")
        self.assertFalse(self.hdll.exists())
        self.assertEqual(self.requests, [])

    def test_nightly_uses_content_addressed_cache(self):
        self.manifest["tag"] = "nightly"
        self.write_manifest()
        self.compile()
        self.binary = b"new nightly"
        self.digest = hashlib.sha256(self.binary).hexdigest()
        self.manifest["platforms"][self.platform]["sha256"] = self.digest
        self.write_manifest()
        self.assertIn("hlavi_offline", self.compile("hlavi_offline", success=False))
        self.routes[f"/release/{self.asset}"] = (200, {}, self.binary)
        self.compile()
        self.assertEqual(self.hdll.read_bytes(), self.binary)
        self.assertEqual(len(self.requests), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
