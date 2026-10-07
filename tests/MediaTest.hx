import haxe.Int64;
import haxe.io.Bytes;
import media.*;

class MediaTest {
    static function check(ok:Bool, message:String):Void {
        if (!ok) throw message;
    }
    static function i(value:Int):Int64 return Int64.ofInt(value);
    static function equal(actual:Int64, expected:Int64, message:String):Void {
        check(Int64.compare(actual, expected) == 0, message);
    }
    static function fails(operation:()->Void, fragment:String):Void {
        var failure:Null<String> = null;
        try operation() catch (error:Dynamic) failure = Std.string(error);
        check(failure != null && failure.indexOf(fragment) >= 0, 'Expected "$fragment", got $failure');
    }
    static function gc():Void {
        hl.Gc.major();
    }
    static function audioInit(timestamp:Int64):AudioDataInit {
        var source = Bytes.alloc(3);
        source.set(0, 128);
        source.set(1, 192);
        source.set(2, 255);
        return new AudioDataInit(AudioSampleFormat.U8, 48000, i(3), i(1), timestamp, source);
    }
    static function audio():Void {
        var timestamp = Int64.make(0x00200000, 7); // Beyond f64's exact integer range.
        var init = audioInit(timestamp);
        gc(); // Only the managed descriptor retains its source buffer now.
        var data = AudioData.create(init);
        equal(data.timestamp(), timestamp, "audio timestamp lost precision");
        equal(data.numberOfFrames(), i(3), "audio frame count");
        equal(data.numberOfChannels(), i(1), "audio channel count");
        check(data.sampleRate() == 48000 && data.format() == AudioSampleFormat.U8, "audio metadata");
        var clone = data.clone();
        data.close();
        data.close();
        fails(() -> { data.numberOfFrames(); }, "closed");
        var options = new AudioDataCopyToOptions(i(0));
        options.format(AudioSampleFormat.F32Planar);
        var output = Bytes.alloc(Int64.toInt(clone.allocationSize(options)));
        clone.copyTo(output, options);
        check(output.length == 12 && output.getFloat(0) == 0 && output.getFloat(4) == 0.5, "PCM conversion");
        fails(() -> clone.copyTo(Bytes.alloc(1), options), "too small");
        // The library's handle table belongs to the VM, not the calling thread.
        var done = new sys.thread.Lock();
        var workerError:Null<String> = null;
        sys.thread.Thread.create(() -> {
            try equal(clone.timestamp(), timestamp, "cross-thread media handle")
            catch (error:Dynamic) workerError = Std.string(error);
            done.release();
        });
        check(done.wait(5), "media worker timed out");
        check(workerError == null, 'media worker: $workerError');
        clone.close();
        fails(() -> { AudioData.create(new AudioDataInit(AudioSampleFormat.U8, 48000, i(-1), i(1), i(0), Bytes.alloc(1))); }, "size");
        Sys.println("audio: PASS");
    }
    static function video():Void {
        var pixels = Bytes.alloc(16);
        for (index in 0...16) pixels.set(index, index * 13);
        var init = new VideoFrameBufferInit(VideoPixelFormat.RGBA, i(2), i(2), i(-9));
        init.duration(i(33333));
        var color = new VideoColorSpaceInit();
        color.primaries(VideoColorPrimaries.Bt709);
        color.fullRange(true);
        init.colorSpace(color);
        var frame = VideoFrame.create(pixels, init);
        pixels.fill(0, pixels.length, 0); // The frame must own a snapshot.
        gc();
        check(frame.format() == VideoPixelFormat.RGBA, "video format");
        equal(frame.timestamp(), i(-9), "negative video timestamp");
        switch frame.duration() {
            case Value(value): equal(value, i(33333), "video duration");
            case Unknown: throw "missing video duration";
        }
        switch frame.visibleRect() {
            case Value(x, y, width, height):
                equal(x, i(0), "rect x"); equal(y, i(0), "rect y");
                equal(width, i(2), "rect width"); equal(height, i(2), "rect height");
        }
        switch frame.colorSpace() {
            case Value(primaries, transfer, matrix, fullRange):
                check(Type.enumEq(primaries, OptionalPrimaries.Value(VideoColorPrimaries.Bt709)), "color primaries");
                check(Type.enumEq(transfer, OptionalTransfer.Unknown), "unknown transfer");
                check(Type.enumEq(matrix, OptionalMatrix.Unknown), "unknown matrix");
                check(Type.enumEq(fullRange, OptionalBool.Value(true)), "color range");
        }
        var copy = new VideoFrameCopyToOptions();
        copy.addLayout(new PlaneLayout(i(4), i(12)));
        var output = Bytes.alloc(Int64.toInt(frame.allocationSize(copy)));
        output.fill(0, output.length, 0xCC);
        var future = frame.copyTo(output, copy);
        frame.close(); // Future result and copied bytes outlive the input handle.
        gc();
        var layouts = future.await();
        check(layouts.count() == 1, "video plane count");
        equal(layouts.offset(0), i(4), "video offset");
        equal(layouts.stride(0), i(12), "video stride");
        for (row in 0...2) for (column in 0...8)
            check(output.get(4 + row * 12 + column) == (row * 8 + column) * 13, "video snapshot/copy");
        check(output.get(0) == 0xCC && output.get(12) == 0xCC, "copy changed padding");
        fails(() -> { layouts.offset(1); }, "index");
        layouts.close();
        layouts.close();
        fails(() -> { layouts.count(); }, "closed");
        var small = VideoFrame.create(Bytes.alloc(4), new VideoFrameBufferInit(VideoPixelFormat.RGBA, i(1), i(1), i(0)));
        var rejected = small.copyTo(Bytes.alloc(0), new VideoFrameCopyToOptions());
        check(rejected.isReady() && rejected.isRejected(), "invalid copy must reject its Future");
        fails(() -> { rejected.await(); }, "too small");
        switch small.duration() { case Unknown: case Value(_): throw "unknown duration became known"; }
        small.close();
        Sys.println("video and futures: PASS");
    }
    static function chunks():Void {
        var bytes = Bytes.ofHex("0011223344");
        var init = new EncodedAudioChunkInit(EncodedChunkType.Key, i(-7), bytes);
        init.duration(i(0));
        var audio = EncodedAudioChunk.create(init);
        var video = EncodedVideoChunk.create(new EncodedVideoChunkInit(EncodedChunkType.Delta, i(9), bytes));
        bytes.set(0, 255);
        gc();
        equal(audio.timestamp(), i(-7), "chunk timestamp");
        equal(video.byteLength(), i(5), "chunk length");
        check(audio.kind() == EncodedChunkType.Key && video.kind() == EncodedChunkType.Delta, "chunk kinds");
        switch audio.duration() { case Value(value): equal(value, i(0), "zero duration"); case Unknown: throw "lost zero duration"; }
        switch video.duration() { case Unknown: case Value(_): throw "lost unknown duration"; }
        var copied = Bytes.alloc(7);
        copied.fill(0, 7, 0xAA);
        video.copyTo(copied);
        check(copied.sub(0, 5).toHex() == "0011223344" && copied.get(6) == 0xAA, "chunk snapshot/copy");
        fails(() -> audio.copyTo(Bytes.alloc(1)), "too small");
        audio.close(); video.close(); audio.close(); video.close();
        fails(() -> { video.timestamp(); }, "closed");
        Sys.println("encoded chunks: PASS");
    }
    static function equalizer():Void {
        var eq = AudioEqualizer.create(2);
        check(eq.bandCount() == 2 && !eq.bandEnabled(0), "equalizer initial bands");
        eq.setBand(0, 1000, 6, 2);
        check(eq.bandFrequency(0) == 1000 && eq.bandGain(0) == 6 && eq.bandQ(0) == 2, "equalizer band settings");
        fails(() -> eq.setBand(-1, 1000, 0, 1), "index");
        fails(() -> eq.setBand(0, 1000, 25, 1), "gain");
        var source = Bytes.alloc(4800 * 4);
        for (sample in 0...4800) source.setFloat(sample * 4, 0.1 * Math.sin(2 * Math.PI * 1000 * sample / 48000));
        var input = AudioData.create(new AudioDataInit(AudioSampleFormat.F32, 48000, i(4800), i(1), i(0), source));
        var processed = eq.process(input);
        var output = Bytes.alloc(source.length);
        processed.copyTo(output, new AudioDataCopyToOptions(i(0)));
        var originalPower = 0.0;
        var processedPower = 0.0;
        for (sample in 2400...4800) {
            var a = source.getFloat(sample * 4);
            var b = output.getFloat(sample * 4);
            originalPower += a * a; processedPower += b * b;
        }
        var gainDb = 10 * Math.log(processedPower / originalPower) / Math.log(10);
        check(Math.abs(gainDb - 6) < 0.01, 'equalizer frequency gain $gainDb');
        processed.close();
        eq.setPreamp(-6);
        check(eq.preamp() == -6, "equalizer preamp");
        eq.setBypass(true);
        check(eq.bypassed(), "equalizer bypass");
        eq.reset();
        var bypassed = eq.process(input);
        eq.close(); eq.close(); input.close();
        bypassed.copyTo(output, new AudioDataCopyToOptions(i(0)));
        check(output.compare(source) == 0, "equalizer bypass/source ownership");
        bypassed.close();
        fails(() -> { eq.bandCount(); }, "closed");
        Sys.println("equalizer: PASS");
    }
    static function main():Void {
        audio();
        video();
        chunks();
        equalizer();
        gc();
        Sys.println("PASS");
    }
}
