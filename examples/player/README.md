# Haxe video player

The application is entirely Haxe:

- **hlavi** opens the file, decodes video, plays audio, and owns the playback clock.
- **hlwgpu** uploads each `VideoFrame` to a texture and renders it with aspect-preserving letterboxing.
- **hlwindow** owns the window, GPU surface handles, and input events.

Native playback uses AVFoundation on macOS/iOS, Media Foundation on Windows,
MediaExtractor/MediaCodec + ImageReader + AAudio on Android, and system
GStreamer on Linux. The Haxe desktop example runs on macOS, Linux, and Windows;
mobile embedding hosts use the same generated API.
This is native playback without FFmpeg. Linux requires GStreamer 1.20+ and
non-FFmpeg decoders for the media: for this H.264/AAC example, OpenH264 (or VA),
FAAD (or FDK AAC), the H.264 parser, conversion plugins, and an audio sink.
The playback pipeline filters gst-libav before format negotiation. Video frames are copied through a reused
Haxe byte buffer; GPU texture sharing is a future optimization.

## Run with the local libraries

From the hlavi repository:

```sh
python3 scripts/run_player.py
python3 scripts/run_player.py /path/to/movie.mp4
```

The default asset is `examples/assets/30903-383991331.mp4`. The runner compiles
Haxe and uses the already-built local libraries and Ash executable. It never
invokes Rust unless the library developer explicitly supplies `--build`.
Use `--vm /path/to/ash` or `--runtime hashlink --vm /path/to/hl` for another VM.
Stock HashLink also needs the `ash-future` extension (`--future-hdll`).

Controls:

| Input | Action |
|---|---|
| Space | Pause/resume; restart after the end |
| Left / Right | Seek backward/forward five seconds |
| Home | Seek to the start |
| Click the bottom bar | Seek to a position in the file |
| M | Mute/unmute |
| E | Toggle the bass/treble equalizer preset |
| F | Toggle fullscreen |
| Escape | Close |

The title shows the playback position and state. The window stays open at the
last frame until closed or restarted. Resizing preserves the video's aspect
ratio. The example closes frames and plane-layout results promptly, reuses the
upload buffer/texture, and releases media/GPU/window resources on exit.

## Application developers: prebuilt Haxelibs

Install `hlavi.zip` from the hlavi GitHub Actions release, along with the
`hlwgpu.zip`, `hlwindow.zip`, and `ash-future.zip` release packages, then compile
from this example checkout:

```sh
haxe examples/player/player.hxml
ash target/player/player.hl examples/assets/30903-383991331.mp4
```

No Rust, C, custom native functions, or bridge code is required in an application.
hlavi's `NativeInstall` macro downloads the matching host library from that
release, verifies its checksum, caches it, and stages it beside the bytecode.
The other Haxelib macros stage their native libraries too. Stock
HashLink builds add `-D ash_future_stock` and expose that directory through the
OS library loader path as described in hlavi's README.

The public playback API is `media.MediaPlayer`: `open`, `play`, `pause`, `seek`,
`setVolume`, `setEqualizer`, `clearEqualizer`, timing/state getters, `pollFrame`, `takeFrame`, and `close`.
`pollFrame` keeps at most one decoded frame until `takeFrame` transfers it to
the caller. The caller uses the standard `VideoFrame.copyTo` and `close` methods.
AVFoundation's audio and video share one native clock. Polling late skips old
video frames instead of growing a queue or delaying audio.

Drive playback on the window's main event-loop thread and keep pumping events;
the native library handles asynchronous loading and seeking. `position` and
`duration` are seconds; `VideoFrame.timestamp` remains integer microseconds.
This initial renderer assumes ordinary SDR video with no track rotation, as in
the supplied sample.

## Library development and verification

```sh
# Rebuild native libraries only when their implementations change.
python3 scripts/run_player.py --build --offline

# Exercises decode/render, pause, seek, resize, volume, resume, EOF,
# equalizer updates and source-handle ownership, invalid inputs, frame ownership, and closed-handle errors.
python3 scripts/run_player.py --self-test

# Optional window-only screenshot (requires macOS Screen Recording access).
python3 scripts/run_player.py --seconds 5 --capture /tmp/player.png

# Verify release packaging and NativeInstall's download/cache flow.
python3 scripts/test_distribution.py
```

## Validation

The same Haxe player and supplied 1920×1080 H.264/AAC file passed the integration
check on macOS ARM64/Ash and Linux x86_64/Ash on the NUC's Wayland monitor.
Native playback also passed on the iOS 26.4 simulator and Android API 36 AVD.
Windows and the generated adapters compile for their targets; Windows playback
still needs a runtime test on a Windows machine. Mobile checks exercise the
native library; the desktop Haxe example is not a packaged mobile application.

GitHub Actions produces the release binaries for each supported target.
Linux users still need compatible system libraries and GStreamer plugins;
the Linux binary is not a static, distribution-independent build.
