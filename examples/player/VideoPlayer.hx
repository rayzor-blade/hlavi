import gpu.*;
import media.MediaPlayer;
import media.AudioEqualizer;
import media.PlaybackState;
import media.VideoFrame;
import media.VideoFrameCopyToOptions;
import media.VideoPixelFormat;
import window.Window;
import window.WindowAttributes;
import window.KeyCode;
import haxe.Int64;
import haxe.io.Bytes;

/** Native audio/video playback through hlavi, presented by hlwgpu in hlwindow. */
class VideoPlayer {
    var window:Window = 0;
    var instance:GpuInstance = 0;
    var adapter:GpuAdapter = 0;
    var device:GpuDevice = 0;
    var surface:GpuSurface = 0;
    var queue:GpuQueue = 0;
    var shader:GpuShader = 0;
    var pipeline:GpuPipeline = 0;
    var sampler:GpuSampler = 0;
    var display:GpuBuffer = 0;
    var displayBytes = Bytes.alloc(16);
    var texture:GpuTexture = 0;
    var textureView:GpuTextureView = 0;
    var group:GpuBindGroup = 0;
    var player:MediaPlayer = 0;
    var equalizer:AudioEqualizer = 0;
    var eqEnabled = false;
    var format:TextureFormat;
    var alpha:AlphaMode;
    var pixels:Bytes;
    var copy = new VideoFrameCopyToOptions();
    var videoWidth = 0;
    var videoHeight = 0;
    var frames = 0;
    var presented = 0;
    var paused = false;
    var muted = false;
    var closed = false;
    var dirty = true;
    var mouseX = 0.0;
    var mouseY = 0.0;
    var lastTimestamp = 0.0;
    var titleAt = 0.0;
    var source:String;

    public function new() {}
    static function check(ok:Bool, message:String):Void { if (!ok) throw message; }

    // Polling before await follows hlwindow's GPU example, avoiding a missed
    // native Ash Future wake while the window owns the main event loop.
    static function ready<T>(future:ash.Future<T>):T {
        var deadline = Sys.time() + 20;
        while (!future.isReady()) {
            check(Sys.time() < deadline, "GPU initialization timed out");
            Sys.sleep(0.001);
        }
        return future.await();
    }
    static function rejects(operation:()->Void):Void {
        var failed = false;
        try operation() catch (_:Dynamic) failed = true;
        check(failed, "invalid media operation did not raise");
    }
    function configure():Void {
        if (window.width() == 0 || window.height() == 0) return;
        var config = new GpuSurfaceConfiguration(format, window.width(), window.height());
        config.presentMode(PresentMode.Fifo);
        config.alphaMode(alpha);
        device.configureSurfaceWith(surface, config);
        dirty = true;
    }
    function open(path:String):Void {
        source = haxe.io.Path.withoutDirectory(path);
        var attributes = new WindowAttributes();
        attributes.title('hlavi — $source');
        attributes.width(960);
        attributes.height(540);
        window = Window.open(attributes);
        check(window.valid(), "could not open the player window");
        instance = new GpuInstance();
        surface = instance.surface(window.platform(), window.raw(0), window.raw(1), window.raw(2), window.raw(3));
        check(surface.valid(), "could not create the window's GPU surface");
        var options = new GpuRequestAdapterOptions();
        options.compatibleSurface(surface);
        options.powerPreference(gpu.Power.LowPower);
        adapter = ready(instance.requestAdapterWith(options));
        check(adapter.valid(), "no compatible GPU adapter");
        device = ready(adapter.requestDevice());
        check(device.valid(), "could not create the GPU device");
        queue = device.queue();
        var caps = surface.capabilities(adapter);
        format = surface.preferredFormat(adapter);
        // Prefer an sRGB target; sampling an sRGB texture then preserves the
        // decoded video's transfer curve through linear filtering/rendering.
        for (i in 0...caps.formatCount()) {
            var candidate = caps.format(i);
            if (candidate == TextureFormat.Bgra8unormSrgb || candidate == TextureFormat.Rgba8unormSrgb) {
                format = candidate;
                break;
            }
        }
        alpha = caps.alphaMode(0);
        caps.destroy();
        configure();
        display = device.createBuffer(new GpuBufferDescriptor(16, BufferUsage.UNIFORM | BufferUsage.COPY_DST));
        shader = device.createShader('
            @group(0) @binding(0) var movie: texture_2d<f32>;
            @group(0) @binding(1) var filtering: sampler;
            @group(0) @binding(2) var<uniform> display: vec4<f32>;
            struct Vertex { @builtin(position) position: vec4<f32>, @location(0) uv: vec2<f32> };
            @vertex fn vs(@builtin(vertex_index) index: u32) -> Vertex {
                let corner = vec2<f32>(f32((index << 1u) & 2u), f32(index & 2u));
                var out: Vertex;
                out.position = vec4<f32>(corner * 2.0 - 1.0, 0.0, 1.0);
                out.uv = vec2<f32>(corner.x, 1.0 - corner.y);
                return out;
            }
            @fragment fn fs(in: Vertex) -> @location(0) vec4<f32> {
                var uv = in.uv;
                // display: movie aspect, window aspect, progress, window height.
                if (display.y > display.x) { uv.x = (uv.x - 0.5) * display.y / display.x + 0.5; }
                else { uv.y = (uv.y - 0.5) * display.x / display.y + 0.5; }
                var color = textureSample(movie, filtering, clamp(uv, vec2<f32>(0.0), vec2<f32>(1.0)));
                if (any(uv < vec2<f32>(0.0)) || any(uv > vec2<f32>(1.0))) {
                    color = vec4<f32>(0.012, 0.014, 0.018, 1.0);
                }
                if (in.uv.y > 1.0 - 10.0 / display.w) {
                    color = select(vec4<f32>(0.08, 0.1, 0.12, 1.0), vec4<f32>(0.1, 0.72, 0.55, 1.0), in.uv.x <= display.z);
                }
                return color;
            }
        ');
        var builder = device.pipeline();
        builder.shader(shader, "vs", "fs");
        builder.target(format, ColorWrite.ALL);
        pipeline = builder.build();
        builder.destroy();
        check(pipeline.valid(), "video render pipeline failed");
        var descriptor = new GpuSamplerDescriptor();
        descriptor.magFilter(FilterMode.Linear);
        descriptor.minFilter(FilterMode.Linear);
        sampler = device.sampler(descriptor);
        player = MediaPlayer.open(path);
        equalizer = AudioEqualizer.create(3);
        equalizer.setBand(0, 100, 6, 0.7);
        equalizer.setBand(1, 1000, -2, 1);
        equalizer.setBand(2, 8000, 3, 0.7);
        equalizer.setPreamp(-9); // Headroom for boosted bands.
        equalizer.setBypass(true);
        player.setEqualizer(equalizer);
        player.play();
        Sys.println('Playing $source on ${adapter.name()}');
        Sys.println("Space: pause/resume · ←/→: seek 5s · Home: restart · M: mute · E: equalizer · F: fullscreen · Esc: close");
        Sys.println("Click the seek bar at the bottom of the window to seek.");
    }
    function upload(frame:VideoFrame):Void {
        check(frame.format() == VideoPixelFormat.BGRA, "player did not return BGRA pixels");
        var width = Int64.toInt(frame.codedWidth());
        var height = Int64.toInt(frame.codedHeight());
        if (texture == 0 || width != videoWidth || height != videoHeight) {
            if (group != 0) group.destroy();
            if (textureView != 0) textureView.destroy();
            if (texture != 0) texture.destroy();
            videoWidth = width;
            videoHeight = height;
            pixels = Bytes.alloc(width * height * 4);
            var size = new GpuExtent3D(width);
            size.height(height);
            var srgb = format == TextureFormat.Bgra8unormSrgb || format == TextureFormat.Rgba8unormSrgb;
            texture = device.texture(new GpuTextureDescriptor(size,
                srgb ? TextureFormat.Bgra8unormSrgb : TextureFormat.Bgra8unorm,
                TextureUsage.COPY_DST | TextureUsage.TEXTURE_BINDING));
            textureView = texture.createView(new GpuTextureViewDescriptor());
            var bindings = new GpuBindings();
            bindings.texture(textureView);
            bindings.sampler(sampler);
            bindings.buffer(display);
            group = device.bindGroup(pipeline, 0, bindings);
            bindings.destroy();
            check(texture.valid() && group.valid(), "could not create the video texture");
            Sys.println('Video: ${width}x${height}');
        }
        var layouts = frame.copyTo(pixels, copy).await();
        layouts.close();
        queue.writeTexture(texture, pixels, width, height, width * 4);
        lastTimestamp = Std.parseFloat(Int64.toStr(frame.timestamp())) / 1000000.0;
        frames++;
        dirty = true;
    }
    function render():Void {
        if (!dirty || window.width() == 0 || window.height() == 0) return;
        var view = surface.acquire();
        if (!view.valid()) { configure(); return; }
        var encoder = device.encoder();
        encoder.passColour(view, 0.012, 0.014, 0.018, 1.0);
        encoder.passBegin();
        if (texture != 0) {
            displayBytes.setFloat(0, videoWidth / videoHeight);
            displayBytes.setFloat(4, window.width() / window.height());
            var duration = player.duration();
            displayBytes.setFloat(8, duration > 0 ? Math.min(1, player.position() / duration) : 0);
            displayBytes.setFloat(12, window.height());
            queue.writeBuffer(display, 0, displayBytes, 16);
            encoder.renderSetPipeline(pipeline);
            encoder.renderSetBindGroup(0, group);
            encoder.renderDraw(3, 1);
        }
        encoder.renderEnd();
        encoder.submit(queue); // submit consumes the encoder; present consumes the surface view.
        queue.presentSurface(surface);
        dirty = false;
        presented++;
    }
    function seek(seconds:Float):Void {
        player.seek(Math.max(0, Math.min(player.duration(), seconds)));
        dirty = true;
    }
    function key(code:KeyCode):Void {
        switch code {
            case Space:
                if (player.state() == PlaybackState.Ended) {
                    seek(0); paused = false; player.play();
                } else {
                    paused = !paused;
                    if (paused) player.pause(); else player.play();
                }
            case ArrowLeft: seek(player.position() - 5);
            case ArrowRight: seek(player.position() + 5);
            case Home: seek(0);
            case KeyM:
                muted = !muted;
                player.setVolume(muted ? 0 : 1);
            case KeyE:
                eqEnabled = !eqEnabled;
                equalizer.setBypass(!eqEnabled);
                player.setEqualizer(equalizer); // Copies settings; preserves player history.
                Sys.println(eqEnabled ? "Equalizer on (bass/treble preset, -9 dB preamp)" : "Equalizer bypassed");
            case KeyF: window.setFullscreen(!window.isFullscreen());
            case Escape: closed = true;
            default:
        }
    }
    static function clock(seconds:Float):String {
        var value = Std.int(seconds);
        return Std.int(value / 60) + ":" + StringTools.lpad(Std.string(value % 60), "0", 2);
    }
    function screenshot(path:String):Void {
        check(Sys.systemName() == "Mac", "--capture currently uses macOS screencapture");
        var scale = window.scaleFactor();
        var left = window.x() + (window.outerWidth() - window.width()) / 2;
        var top = window.y() + window.outerHeight() - window.height();
        var region = [left, top, window.width(), window.height()].map(v -> Std.string(Math.round(v / scale))).join(",");
        check(Sys.command("screencapture", ["-x", "-R", region, path]) == 0, "window capture failed");
    }
    function run(path:String, seconds:Float, capture:String, selfTest:Bool):Void {
        open(path);
        var started = Sys.time();
        var phase = 0;
        var phaseAt = started;
        var pausePosition = 0.0;
        var seekTarget = 0.0;
        var seekFrames = 0;
        window.requestRedraw();
        while (!closed && (seconds <= 0 || Sys.time() - started < seconds)) {
            switch window.wait(0.01) {
                case Closed | Destroyed: closed = true;
                case Resized(_, _) | ScaleFactorChanged(_): configure();
                case RedrawRequested: dirty = true;
                case CursorMoved(x, y, _): mouseX = x; mouseY = y;
                case MouseInput(Pressed, Left, _) if (mouseY >= window.height() - 24 * window.scaleFactor()):
                    seek(player.duration() * mouseX / window.width());
                case KeyboardInput(_, Input(Code(code), _, _, _, Pressed, false, _), _): key(code);
                default:
            }
            if (closed) break;
            if (player.pollFrame()) {
                var frame = player.takeFrame();
                try upload(frame) catch (error:Dynamic) { frame.close(); throw error; }
                frame.close();
            }
            render();
            var now = Sys.time();
            var state = player.state();
            if (now >= titleAt) {
                var status = state == PlaybackState.Ended ? "Ended" : paused ? "Paused" : state == PlaybackState.Buffering ? "Buffering" : "Playing";
                window.setTitle('$source  ·  ${clock(player.position())} / ${clock(player.duration())}  ·  $status${muted ? " · Muted" : ""}${eqEnabled ? " · EQ" : ""}');
                titleAt = now + 0.25;
            }
            check(frames > 0 || now - started < 20, "no decoded video frame within 20 seconds");
            if (capture != null && frames > 5) { screenshot(capture); capture = null; }
            // A bounded integration exercise of the real window/GPU/audio path.
            if (selfTest) {
                switch phase {
                    case 0 if (frames >= 8 && player.position() > 0.25):
                        check(player.duration() > 1, "missing media duration");
                        rejects(() -> player.seek(-1));
                        rejects(() -> player.setVolume(2));
                        rejects(() -> { player.takeFrame(); });
                        key(KeyCode.KeyE);
                        check(eqEnabled, "equalizer enable failed");
                        player.pause(); paused = true;
                        pausePosition = player.position(); phaseAt = now; phase = 1;
                    case 1 if (now - phaseAt > 0.3):
                        check(Math.abs(player.position() - pausePosition) < 0.1, "pause did not stop the media clock");
                        seekTarget = player.duration() / 2;
                        seek(seekTarget); seekFrames = frames;
                        window.setSize(720, 540);
                        player.setVolume(0); check(player.volume() == 0, "mute failed");
                        phase = 2;
                    case 2 if (frames > seekFrames && state != PlaybackState.Buffering):
                        check(Math.abs(lastTimestamp - seekTarget) < 0.2, 'seek frame $lastTimestamp does not match $seekTarget');
                        player.setVolume(1); check(player.volume() == 1, "unmute failed");
                        // A temporary source can be closed after its settings are copied.
                        var temporary = AudioEqualizer.create(1);
                        temporary.setBand(0, 500, -12, 1);
                        player.setEqualizer(temporary);
                        temporary.close();
                        player.clearEqualizer();
                        player.setEqualizer(equalizer);
                        player.play(); paused = false; phaseAt = now; phase = 3;
                    case 3 if (now - phaseAt > 0.5):
                        check(player.position() > seekTarget + 0.2, "resume did not advance the clock");
                        seek(player.duration() - 0.25); phase = 4;
                    case 4 if (state == PlaybackState.Ended):
                        check(frames > 10 && presented > 10, "not enough frames were rendered");
                        check(device.takeError() == null, "GPU reported a validation error");
                        Sys.println("PLAYER PASS: decode, render, pause, seek, resize, volume, equalizer, resume, end-of-file");
                        player.close();
                        rejects(() -> { player.position(); });
                        player.close();
                        player = 0;
                        phase = 5; closed = true;
                    default:
                }
                check(now - started < 20, 'player self-test stalled in phase $phase');
            }
        }
        if (selfTest) check(phase == 5, 'player test stopped in phase $phase');
        check(frames > 0, "no video frames decoded");
        Sys.println('Decoded $frames frame(s), presented $presented frame(s).');
    }
    function close():Void {
        if (player != 0) player.close();
        if (equalizer != 0) equalizer.close();
        if (group != 0) group.destroy();
        if (textureView != 0) textureView.destroy();
        if (texture != 0) texture.destroy();
        if (sampler != 0) sampler.destroy();
        if (display != 0) display.destroy();
        if (pipeline != 0) pipeline.destroy();
        if (shader != 0) shader.destroy();
        if (surface != 0) surface.destroy();
        if (device != 0) device.destroy();
        if (adapter != 0) adapter.destroy();
        if (instance != 0) instance.destroy();
        if (window != 0) window.close();
    }
    static function main():Void {
        var args = Sys.args();
        check(args.length > 0, "usage: VideoPlayer <file> [--seconds N] [--capture image.png] [--self-test]");
        var seconds = 0.0;
        var capture:String = null;
        var selfTest = false;
        var index = 1;
        while (index < args.length) {
            switch args[index++] {
                case "--seconds": seconds = Std.parseFloat(args[index++]); check(Math.isFinite(seconds) && seconds > 0, "invalid --seconds");
                case "--capture": capture = args[index++];
                case "--self-test": selfTest = true;
                case other: throw 'unknown argument $other';
            }
        }
        var app = new VideoPlayer();
        try app.run(args[0], seconds, capture, selfTest) catch (error:Dynamic) {
            app.close(); Sys.println('PLAYER FAIL: $error'); Sys.exit(1);
        }
        app.close();
    }
}
