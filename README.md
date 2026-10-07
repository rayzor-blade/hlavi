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

## Prebuilt package for application developers

Install the platform's `hlavi.zip` with `haxelib install /path/to/hlavi.zip`
and use `-lib hlavi`. The archive includes generated Haxe classes and
`xavi.hdll`; applications need no Rust/C compiler or custom native bridge.
Install the matching `ash-future` package for the Future API. See the player
example for a build using prebuilt hlwgpu and hlwindow packages too.

Library maintainers produce this archive with `python3 scripts/build.py --release`
and `python3 scripts/package_haxelib.py`. Available native builds are packaged
from `native/`; build and package each supported host before distribution.

## Library development with sibling checkouts

This initial development setup uses xavi's local checkout because its current
commits have not yet been published. Keep these repositories beside one another:

```text
workspace/
  hlavi/
  xavi/
  x-idl/
  ash/       # optional: local VM and ash-future sources for tests
```

Use the matching xavi working tree with the new `MediaPlayer` API and its
x-idl checkout (the initial generator revision is `bf1ab2f`). The other Rust dependencies are recorded
in `Cargo.lock`. Once xavi is published, its path dependencies can be replaced
with a shared pinned Git revision as in hlwgpu.

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

The haxelib macro stages the host's `xavi.hdll` beside the bytecode. Override
its source with `-D hlavi_hdll=/path/to/xavi.hdll`; use `-D hlavi_no_hdll` when
an embedding host supplies it. HLC builds skip automatic staging and need a
separate static-link integration.

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

## Runtime tests

After building:

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
