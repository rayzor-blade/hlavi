package hlavi.macro;

#if macro
import haxe.io.Path;
import haxe.macro.Compiler;
import haxe.macro.Context;
import sys.FileSystem;
import sys.io.File;
import sys.io.Process;

/** Stage xavi.hdll beside HashLink bytecode. Derived from hlwgpu's installer. */
class NativeInstall {
    public static function stage():Void {
        if (!Context.defined("hl") || Context.defined("hlc") || Context.defined("hlavi_no_hdll")) return;
        Context.onAfterGenerate(() -> {
            var source = Context.definedValue("hlavi_hdll");
            if (source == null) {
                var module = Context.resolvePath("hlavi/macro/NativeInstall.hx");
                var root = Path.directory(Path.directory(Path.directory(Path.directory(module))));
                source = Path.join([root, "native", hostPlatform(), "xavi.hdll"]);
            }
            if (!FileSystem.exists(source) || FileSystem.isDirectory(source)) {
                Context.fatalError('No xavi.hdll at $source. Install a prebuilt hlavi package for this platform, or set -D hlavi_hdll=/path/to/xavi.hdll.', Context.currentPos());
                return;
            }
            var destination = Path.join([Path.directory(Compiler.getOutput()), "xavi.hdll"]);
            if (FileSystem.fullPath(source) != FileSystem.absolutePath(destination))
                File.copy(source, destination);
        });
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
            if (status != 0) throw "hlavi could not detect the CPU architecture";
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
