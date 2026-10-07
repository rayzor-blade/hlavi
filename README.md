# hlavi

Play media files with synchronized audio and video, work with video frames
and PCM audio, and manage encoded media chunks from Haxe on Ash and HashLink.
hlavi exposes [xavi](https://github.com/rayzor-blade/xavi)'s media API through
the shared `media` package.

## Quick start

With Haxe and Ash installed, download `hlavi.zip` from the
[hlavi releases](https://github.com/rayzor-blade/hlavi/releases) and
`ash-future.zip` from the [Ash releases](https://github.com/rayzor-blade/ash/releases).
Install both packages:

```sh
haxelib install /path/to/ash-future.zip
haxelib install /path/to/hlavi.zip
```

Create `Main.hx` to work with both an RGBA video frame and a PCM audio buffer.
This example creates media data in memory, reads its dimensions and frame
count, and releases it:

```haxe
import haxe.Int64;
import haxe.io.Bytes;
import media.AudioData;
import media.AudioDataInit;
import media.AudioSampleFormat;
import media.VideoFrame;
import media.VideoFrameBufferInit;
import media.VideoPixelFormat;

class Main {
    static function main() {
        // A 2 × 2 video frame containing four opaque red pixels.
        var pixels = Bytes.alloc(2 * 2 * 4);
        for (pixel in 0...4) {
            pixels.set(pixel * 4, 255);     // Red
            pixels.set(pixel * 4 + 3, 255); // Alpha
        }
        var video = VideoFrame.create(pixels, new VideoFrameBufferInit(
            VideoPixelFormat.RGBA,
            Int64.ofInt(2), Int64.ofInt(2), Int64.ofInt(0)
        ));
        trace(video.codedWidth());  // 2
        trace(video.codedHeight()); // 2
        video.close();

        // A mono PCM buffer with 1,024 samples at 48 kHz.
        var audio = AudioData.create(new AudioDataInit(
            AudioSampleFormat.S16, 48000,
            Int64.ofInt(1024), Int64.ofInt(1), Int64.ofInt(0),
            Bytes.alloc(2048)
        ));
        trace(audio.numberOfFrames()); // 1024
        audio.close();
    }
}
```

Compile and run it:

```sh
haxe -lib hlavi -main Main -hl main.hl
ash main.hl
```

`NativeInstall` automatically downloads and stages the matching native library
when Haxe compiles your program. Applications need no Rust/C compiler or native
bridge. For stock HashLink, see [runtime behavior](#runtime-behavior).

## Play a video with sound

[The video player](examples/player/README.md) uses `media.MediaPlayer` for
native decoding, audio output, playback timing, pause, and seeking. hlwgpu
renders its video frames, and hlwindow provides the window and input, entirely
from Haxe. Install the `hlwgpu.zip` and `hlwindow.zip` release packages
alongside the packages above, then run from the hlavi repository:

```sh
haxe examples/player/player.hxml
ash target/player/player.hl examples/assets/30903-383991331.mp4
```

It plays the included video with sound and supports pause, seek, mute,
fullscreen, and resizing with the aspect ratio preserved. The desktop example
runs on macOS, Windows, and Linux; mobile hosts use the same native playback API.
See the [example guide](examples/player/README.md) for controls and platform
requirements.

## Equalize audio

Use the same equalizer for PCM processing and the video player's sound:

```haxe
import media.AudioEqualizer;

var eq = AudioEqualizer.create(3);
eq.setBand(0, 100, 6, 0.7);    // Index, center frequency (Hz), gain (dB), Q.
eq.setBand(1, 1000, -2, 1);
eq.setBand(2, 8000, 3, 0.7);
eq.setPreamp(-9);              // Leave headroom for boosted frequencies.

// Given an open MediaPlayer:
player.setEqualizer(eq);
// Later changes are explicit: modify eq, then call setEqualizer again.
// player.clearEqualizer() restores flat playback.

// Alternatively, given a decoded AudioData block:
var filtered = eq.process(block);
// Send filtered to AudioEncoder or a MediaQueue, then close your handle.
filtered.close();
eq.close();                    // The player keeps its own settings and history.
```

The [video player](examples/player/README.md) toggles a bass/treble preset with
**E**. Playback uses the shared native DSP on macOS, iOS, Windows, Android, and
Linux; it adds no FFmpeg dependency. Applications only call Haxe methods.

An equalizer supports 1–16 peaking bands. Frequency is 1–96000 Hz, gain is
−24…+24 dB, and Q is 0.1–20 (larger values make a narrower band). Bands start
disabled; `disableBand(index)` disables one. `setPreamp` accepts −60…0 dB;
`setBypass(true)` bypasses both bands and preamp. Settings changes transition
over 10 ms. Bands at or above half the input sample rate are inactive.

`process` returns owned interleaved F32 with the input timing and channel count.
Keep one equalizer per PCM stream: history carries across contiguous blocks,
resets on timestamp gaps or format changes, and can be cleared with `reset()`.
It accepts integer/float and planar/interleaved PCM, 1000–384000 Hz and 1–32
channels, up to 64 MiB per converted block. Processing preserves finite values
above full scale; native playback clips at its output boundary. Reduce preamp
when boosting to avoid clipping. Close every returned audio block.

## Current API

The generated native surface currently provides:

- `AudioData`: owned PCM, format conversion, copying, slicing, gain, mixing, and retiming.
- `AudioEqualizer`: stateful multiband PCM filtering and copied playback settings.
- `VideoFrame`: owned CPU pixels, metadata, copying, cropping, resizing, blending, and retiming.
- `EncodedAudioChunk` and `EncodedVideoChunk`: owned encoded bytes and timing.
- `PlaneLayouts`: the result of `VideoFrame.copyTo`, carried by `ash.Future`.
- `MediaPlayer`: native file playback with audio, a shared playback clock,
  pause/seek/volume controls, and polled video frames on macOS, iOS, Windows, Android, and Linux.

- `MediaQueue`: bounded audio/video/chunk/byte queues with explicit backpressure.
- `AudioEncoder`, `VideoEncoder`, `AudioDecoder`, `VideoDecoder`, and
  `CodecConfiguration`: native codec sessions driven by polling from Haxe.
- `MediaDemuxer` and `MediaMuxer`: incremental MP4 packet reading and writing
  within xavi's current AAC/H.264 codec and container profile.

Device capture, GPU frames, and browser media remain outside this surface.
The adapter includes no FFmpeg dependency or fallback.

## Runtime behavior

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

## Native installation

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

## Architecture

xavi owns the IDL, Rust media implementation, platform codecs, container
writers, and generator. hlavi owns the Ash/HashLink adapter, generated Haxe
sources, native packaging, and runtime integration tests. Both runtimes load
the same native library as `xavi.hdll`. The shared `hl_xidl` carriers come from
[hlwgpu](https://github.com/rayzor-blade/hlwgpu).

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

`release-sources.json` selects a versioned or nightly **xavi SDK release** and
its exact source revision, plus the HashLink source for the Windows import
library. Every desktop and mobile job downloads `xavi-sdk.zip` from xavi's
GitHub release, checks `SHA256SUMS`, and verifies its revision and source-file
checksums. x-idl is bundled by xavi; hlavi no longer checks out either project
in CI. The portable SDK compiles into hlavi's native adapter for each target.
Application users still receive finished native libraries via `NativeInstall`.

Change the xavi `tag` to a published `v<version>` or `nightly` and record the
revision from that SDK's `xavi-sdk.json`. Update the pin and regenerated Haxe
sources together when upgrading. Nightly builds are revision-pinned too: if
the rolling asset changes, CI fails rather than mixing different SDKs across
platforms. A release using a newer xavi commit must wait for xavi's publishing
workflow to complete. Use versioned xavi releases for reproducible long-term
builds; the rolling nightly asset is replaced by subsequent builds.

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

For a clean checkout without xavi/x-idl siblings, install the pinned release:

```sh
python3 scripts/fetch_xavi.py
python3 scripts/release_check.py pins --sdk
```

The downloader refuses to overwrite an existing developer checkout. To use
Git siblings, check out xavi's pinned revision and the x-idl revision in
**xavi's** `release-sources.json`; `python3 scripts/release_check.py pins
--checkouts` verifies both. Path dependencies allow local xavi/x-idl changes
during development. CI uses the released SDK and checks generated-source drift.
No Rust/C toolchain is required by end users installing the Haxelib release.

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

Register the local Haxe sources to use this checkout instead of an installed
release package:

```sh
haxelib dev hlavi /path/to/hlavi
haxe -lib hlavi -cp examples -main MediaData -hl media.hl
ash media.hl
```

With the sibling hlwgpu and hlwindow libraries and Ash already built, the local
player runner compiles and launches the example:

```sh
python3 scripts/run_player.py
```

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
