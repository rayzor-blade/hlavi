# hlavi

hlavi packages [xavi](https://github.com/rayzor-blade/xavi)'s media API for
Haxe programs on Ash and HashLink. Both runtimes use the same generated
`media` package and native library, loaded as `xavi.hdll`.

xavi owns the IDL, Rust media implementation, platform codecs, container
writers, and generator. hlavi owns the Ash/HashLink adapter, generated Haxe
sources, native packaging, and runtime integration tests. The shared
`hl_xidl` carriers come from [hlwgpu](https://github.com/rayzor-blade/hlwgpu).

## Current API

The generated native surface currently provides:

- `AudioData`: owned PCM, format conversion, plane copies, and cloning.
- `VideoFrame`: owned CPU pixels, metadata, layout/crop copies, and cloning.
- `EncodedAudioChunk` and `EncodedVideoChunk`: owned encoded bytes and timing.
- `PlaneLayouts`: the result of `VideoFrame.copyTo`, carried by `ash.Future`.
- `MediaPlayer`: native file playback with audio, a shared playback clock,
  pause/seek/volume controls, and polled video frames on macOS, iOS, Windows, Android, and Linux.

xavi's native AAC/H.264 codecs and MP4 writers are available to Rust callers.
Their lower-level worker scheduling, callbacks, streaming queues, and runtime
bindings are not exported to Haxe yet. `MediaPlayer` already exposes complete
file playback through the native framework, independently of those sessions. Device capture,
packet-level container reading, GPU frames, and browser media are also outside this initial
surface. The adapter includes no FFmpeg dependency or fallback.

## Video player example

[The video player](examples/player/README.md) uses hlavi, hlwgpu, and hlwindow
entirely from Haxe. With the local native libraries already built, run:

```sh
python3 scripts/run_player.py
```

It plays `examples/assets/30903-383991331.mp4` with sound, supports pause, seek,
mute and fullscreen, and preserves aspect ratio when resized. The desktop runner supports macOS, Windows, and Linux; mobile hosts use the
same native playback API.

## Install a release

GitHub Actions builds the native libraries and publishes them with `hlavi.zip`
on the [releases page](https://github.com/rayzor-blade/hlavi/releases). Install
that ZIP with `haxelib install /path/to/hlavi.zip` and use `-lib hlavi`.
Install the matching `ash-future` package for the Future API. Applications need
no Rust/C compiler or custom native bridge.

The Haxelib contains the generated Haxe API, `NativeInstall`, and a release
manifest. On the first Haxe compilation, `NativeInstall` downloads the host's
`xavi.hdll`, verifies its SHA-256, caches it, and copies it beside the bytecode.
Later compilations reuse the verified cache. Each package records its exact
release tag and binary hashes, including for nightly builds.

Desktop release targets are macOS ARM64/x86_64, Linux ARM64/x86_64, and Windows
x86_64. Linux still needs system GStreamer and suitable non-FFmpeg decoder
plugins. Separate static archives support iOS ARM64 and ARM64 simulator hosts,
and Android ARM64, ARMv7, and x86_64 hosts. The desktop installer does not
perform mobile host linking.

Native installation options:

| Haxe define | Purpose |
|---|---|
| `-D hlavi_hdll=/path/to/xavi.hdll` | Stage an explicit local build; skip downloading |
| `-D hlavi_offline` | Require a local build or a verified cached binary |
| `-D hlavi_cache=/path/to/cache` | Override the per-user cache directory |
| `-D hlavi_release_url=https://mirror/path` | Use a mirror containing this release's assets and `hdlls.json` |
| `-D hlavi_no_hdll` | Skip installation when an embedding host supplies the library |

The default cache is under `XDG_CACHE_HOME/hlavi`, `~/Library/Caches/hlavi` on
macOS, `~/.cache/hlavi` on Linux, or `%LOCALAPPDATA%/hlavi` on Windows.
Local `native/<platform>/xavi.hdll` developer builds take precedence over
downloads. HLC builds skip automatic staging and use separate static linking.
A Git/source installation fetches the manifest for the version named in
`native/hdlls.json` when no local library is present. Install a release ZIP to
keep the Haxe sources and native binary matched, especially for nightlies.

## Release automation

[The release workflow](.github/workflows/release.yml) builds all desktop and
mobile targets, checks the generated Haxe API, and packages the release. A
`v*` tag publishes that version; the scheduled run publishes a rolling nightly
when the commit changes. A manual run with an empty `release_tag` builds and
validates without publishing. For a manual version release, select the
corresponding existing tag and supply it as `release_tag`.

The workflow publishes `hlavi.zip`, `hdlls.json`, separate
`xavi-<platform>.hdll` assets, and `hlavi-<mobile-platform>.zip` static archives.
The desktop libraries are downloaded by the macro, not bundled in the Haxelib.
Publishing a GitHub release does not upload it to the Haxelib registry.

`release-sources.json` pins the xavi implementation, x-idl generator, and
HashLink source used for the Windows import library. CI checks out those
revisions beside hlavi and uses `Cargo.lock` for Rust dependencies. Update
those pins together with regenerated Haxe sources when upgrading xavi.

Maintainers can test packaging using a directory containing every desktop
release asset built by CI:

```sh
python3 scripts/package_haxelib.py /path/to/release-assets \
  --tag v0.1.0 --revision <full-hlavi-commit>
```

The packager rejects missing or empty assets and embeds their checksums in
the package. It never gathers binaries from a maintainer's local `native/`
folder. The new workflow must complete a publishing run before its download
assets are available.

## Library development with sibling checkouts

Keep these repositories beside one another:

```text
workspace/
  hlavi/
  xavi/
  x-idl/
  ash/       # optional: local VM and ash-future sources for tests
```

Use the revisions in `release-sources.json` to reproduce a release. Path
dependencies also allow local xavi/x-idl changes during development; CI uses
the recorded commits and verifies generated-source drift.

With Rust, Python 3, and the platform build tools installed:

```sh
python3 scripts/build.py
# Optimized build; --offline uses already cached dependencies.
python3 scripts/build.py --release
```

The script runs Cargo with the lockfile, generates Rust primitives under
`OUT_DIR`, updates `haxe/media/*.hx` from xavi, and stages the desktop library
at `native/<platform>/xavi.hdll`. Haxe sources are checked in for consumers;
do not edit generated files by hand.

`--target <Rust target>` supports desktop cross builds and stages static
archives for iOS/Android. Cross builds need the matching Rust target, SDK,
and linker. On Windows, set `HL_LIB_DIR` to the directory containing
`libhl.lib`. Native media codecs use Apple frameworks, Media Foundation,
Android MediaCodec, or system GStreamer on Linux; see xavi for capabilities.
The initial media data operations themselves do not open a codec.

## Use from Haxe

Install the `ash-future` ZIP from the Ash release assets and register this working directory:

```sh
haxelib install /path/to/ash-future.zip
haxelib dev hlavi /path/to/hlavi
haxe -lib hlavi -cp examples -main MediaData -hl media.hl
ash media.hl
```

The Haxelib macro installs the host library as described above. A developer
checkout can use the staged local build from `scripts/build.py`.

```haxe
import haxe.Int64;
import haxe.io.Bytes;
import media.AudioData;
import media.AudioDataInit;
import media.AudioSampleFormat;

var data = AudioData.create(new AudioDataInit(
    AudioSampleFormat.S16, 48000,
    Int64.ofInt(1024), Int64.ofInt(1), Int64.ofInt(0), Bytes.alloc(2048)
));
trace(data.numberOfFrames());
data.close();
```

Counts, byte sizes, and timestamps use `haxe.Int64` to preserve the ABI's full
range. PCM samples use the host's byte order. Media snapshots own their data,
and clones keep storage alive after the original handle is closed. Explicitly
close media, chunks, and returned plane layouts; wrapper collection does not
close handles. A loaded library serves one VM, including its threads. Hosts
embedding multiple independent VMs need a context-selection hook before
sharing this library.

Ash provides the Future ABI. For stock HashLink, add `-D ash_future_stock`
and use the packaged `ash-future` haxelib, which stages `ash_future.hdll`.
Make the bytecode directory visible to the OS library loader (`LD_LIBRARY_PATH`
on Linux, `DYLD_LIBRARY_PATH` on macOS, or `PATH` on Windows). Future errors
raise when awaited, while synchronous validation errors raise at the call.

## Tests

The distribution suite uses the real Haxe compiler and a local HTTP fixture
to check downloads, redirects, checksums, offline/cache behavior, overrides,
and release packaging. It needs Python 3 and Haxe, without Rust or a VM:

```sh
python3 scripts/test_distribution.py
```

After building the native adapter:

```sh
# Defaults to ../ash/target/release/ash and ../ash/haxelib/ash-future.
python3 scripts/test_native.py

# Override the local runtime and Future sources.
python3 scripts/test_native.py --vm /path/to/ash --future /path/to/ash-future

# Run the same suite on stock HashLink with its Future extension.
python3 scripts/test_native.py --runtime hashlink --vm /path/to/hl \
  --future /path/to/ash-future --future-hdll /path/to/ash_future.hdll
```

`--compile-only` checks the selected Haxe runtime configuration and library
staging without executing it. Stock HashLink's JIT requires a supported host
architecture; the initial macOS ARM validation runs on Ash, with the stock
HashLink configuration checked at compile time.

The suite covers exact 64-bit timing, owned snapshots, PCM conversion, video
layout and padding, metadata enums, cloned/stale handles, cross-thread use,
GC retention, error propagation, and Future resolution/rejection. The test
script uses a temporary directory and enforces a runtime timeout.

Rust checks can target this adapter without formatting sibling repositories:

```sh
cargo fmt -p hlavi -- --check
cargo clippy -p hlavi --lib --locked -- -D warnings
```
