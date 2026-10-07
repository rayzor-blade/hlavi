package hlavi.macro;

#if macro
import haxe.Json;
import haxe.crypto.Sha256;
import haxe.io.Bytes;
import haxe.io.Path;
import haxe.macro.Compiler;
import haxe.macro.Context;
import sys.FileSystem;
import sys.io.File;
import sys.io.Process;

/** Download/cache the matching release binary and stage it beside HL bytecode. */
class NativeInstall {
    public static function stage():Void {
        if (!Context.defined("hl") || Context.defined("hlc") || Context.defined("hlavi_no_hdll")) return;
        Context.onAfterGenerate(() -> {
            try {
                var source = Context.definedValue("hlavi_hdll");
                if (source == null) source = resolve();
                if (!isFile(source)) throw 'No xavi.hdll at $source';
                var destination = Path.join([Path.directory(Compiler.getOutput()), "xavi.hdll"]);
                if (FileSystem.fullPath(source) != FileSystem.absolutePath(destination)) File.copy(source, destination);
            } catch (error:Dynamic) {
                Context.fatalError('hlavi: $error', Context.currentPos());
            }
        });
    }

    static function resolve():String {
        var module = Context.resolvePath("hlavi/macro/NativeInstall.hx");
        var root = Path.directory(Path.directory(Path.directory(Path.directory(module))));
        var manifest:Dynamic = Json.parse(File.getContent(Path.join([root, "native/hdlls.json"])));
        var platform = hostPlatform();
        var entry:Dynamic = Reflect.field(manifest.platforms, platform);
        if (entry == null) throw 'No release binary for $platform; supply -D hlavi_hdll=/path/to/xavi.hdll';
        var local = Path.join([root, entry.packagePath]);
        // Library development and explicitly bundled/offline packages take precedence.
        if (isFile(local)) {
            if (entry.sha256 != null && !matches(local, entry.sha256)) throw 'Checksum mismatch in $local';
            return local;
        }
        var tag:String = manifest.tag;
        if (!~/^[A-Za-z0-9][A-Za-z0-9._-]*$/.match(tag)) throw "Invalid release tag in native/hdlls.json";
        var base = Context.definedValue("hlavi_release_url");
        if (base == null) base = 'https://github.com/${manifest.repository}/releases/download/$tag';
        while (StringTools.endsWith(base, "/")) base = base.substr(0, base.length - 1);
        var cache = Path.join([cacheRoot(), tag]);
        if (entry.sha256 == null) {
            // A Git/source installation has the platform catalogue. Release ZIPs
            // already contain the hashes, pinned to the exact CI build.
            var metadata = Path.join([cache, "hdlls.json"]);
            if (!isFile(metadata)) {
                requireNetwork();
                var bytes = download(base + "/hdlls.json");
                var remote:Dynamic = Json.parse(bytes.toString());
                checkRelease(remote, manifest, platform);
                atomicWrite(metadata, bytes);
            }
            var remote:Dynamic = Json.parse(File.getContent(metadata));
            checkRelease(remote, manifest, platform);
            entry = Reflect.field(remote.platforms, platform);
        }
        var digest:String = entry.sha256;
        if (digest == null || !~/^[a-f0-9]{64}$/.match(digest)) throw "Release manifest has no valid SHA-256";
        var source = Path.join([cache, platform, digest, "xavi.hdll"]);
        if (matches(source, digest)) return source;
        requireNetwork();
        Context.info('hlavi: downloading ${entry.releaseAsset} ($tag)', Context.currentPos());
        var bytes = download(base + "/" + entry.releaseAsset);
        if (Sha256.make(bytes).toHex() != digest) throw "Downloaded binary does not match this Haxe package; reinstall the matching release package";
        atomicWrite(source, bytes);
        return source;
    }

    static function checkRelease(remote:Dynamic, expected:Dynamic, platform:String):Void {
        var entry:Dynamic = remote.platforms == null ? null : Reflect.field(remote.platforms, platform);
        var original:Dynamic = Reflect.field(expected.platforms, platform);
        if (remote.tag != expected.tag || remote.repository != expected.repository || entry == null
            || entry.releaseAsset != original.releaseAsset || entry.sha256 == null
            || !~/^[a-f0-9]{64}$/.match(entry.sha256))
            throw "Release manifest does not match this hlavi package";
    }

    static function requireNetwork():Void {
        if (Context.defined("hlavi_offline")) throw "No matching cached binary (hlavi_offline); supply -D hlavi_hdll=/path/to/xavi.hdll";
    }

    static function isFile(path:String):Bool return FileSystem.exists(path) && !FileSystem.isDirectory(path);
    static function matches(path:String, digest:String):Bool return isFile(path) && Sha256.make(File.getBytes(path)).toHex() == digest;

    static function atomicWrite(path:String, bytes:Bytes):Void {
        FileSystem.createDirectory(Path.directory(path));
        var temporary = path + '.${Std.random(0x3fffffff)}.tmp';
        try {
            File.saveBytes(temporary, bytes);
            // Another compiler can finish the same download concurrently.
            if (isFile(path)) {
                if (Sha256.make(File.getBytes(path)).toHex() == Sha256.make(bytes).toHex()) {
                    FileSystem.deleteFile(temporary);
                    return;
                }
                FileSystem.deleteFile(path);
            }
            FileSystem.rename(temporary, path);
        } catch (error:Dynamic) {
            if (isFile(temporary)) FileSystem.deleteFile(temporary);
            // Windows rename can fail if another compiler just installed it.
            if (matches(path, Sha256.make(bytes).toHex())) return;
            throw error;
        }
    }

    static function download(url:String, redirects:Int = 0):Bytes {
        if (redirects > 5) throw "Too many release download redirects";
        var http = new sys.Http(url);
        http.cnxTimeout = 60;
        http.setHeader("User-Agent", "hlavi-NativeInstall");
        var status = 0;
        var problem:String = null;
        var body:Bytes = null;
        http.onStatus = code -> status = code;
        http.onError = message -> problem = message;
        http.onBytes = bytes -> body = bytes;
        http.request(false);
        if ([301, 302, 303, 307, 308].indexOf(status) >= 0) {
            var location:String = null;
            if (http.responseHeaders != null) for (name in http.responseHeaders.keys())
                if (name.toLowerCase() == "location") location = http.responseHeaders.get(name);
            if (location == null) throw "Release redirect has no Location header";
            if (StringTools.startsWith(location, "/")) {
                var origin = ~/^(https?:\/\/[^\/]+)/;
                if (!origin.match(url)) throw "Invalid release URL";
                location = origin.matched(1) + location;
            }
            if (StringTools.startsWith(url, "https:") && !StringTools.startsWith(location, "https:"))
                throw "Release download redirected outside HTTPS";
            return download(location, redirects + 1);
        }
        if (problem != null || status != 200 || body == null)
            throw 'Could not download $url (${problem == null ? Std.string(status) : problem}); check that the release is published, or set -D hlavi_hdll=/path/to/xavi.hdll';
        return body;
    }

    static function cacheRoot():String {
        var custom = Context.definedValue("hlavi_cache");
        if (custom != null) return custom;
        var home = Sys.getEnv("HOME");
        if (home == null) home = Sys.getEnv("USERPROFILE");
        var cache = Sys.getEnv(Sys.systemName() == "Windows" ? "LOCALAPPDATA" : "XDG_CACHE_HOME");
        if (cache == null) {
            if (home == null) throw "Cannot locate the cache directory; set -D hlavi_cache=/path/to/cache";
            cache = Path.join([home, Sys.systemName() == "Mac" ? "Library/Caches" : ".cache"]);
        }
        return Path.join([cache, "hlavi"]);
    }

    static function hostPlatform():String {
        var os = switch (Sys.systemName()) {
            case "Linux": "linux";
            case "Mac": "macos";
            case "Windows": "windows";
            case other: other.toLowerCase();
        };
        var arch:String;
        if (os == "windows") {
            arch = Sys.getEnv("PROCESSOR_ARCHITEW6432");
            if (arch == null) arch = Sys.getEnv("PROCESSOR_ARCHITECTURE");
        } else {
            var process = new Process("uname", ["-m"]);
            arch = StringTools.trim(process.stdout.readAll().toString());
            var status = process.exitCode();
            process.close();
            if (status != 0) throw "Cannot detect the CPU architecture";
        }
        arch = switch (arch == null ? "" : arch.toLowerCase()) {
            case "amd64", "x86_64": "x86_64";
            case "arm64", "aarch64": "aarch64";
            case other: other;
        };
        return '$os-$arch';
    }
}
#end
