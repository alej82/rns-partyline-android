import importlib
import importlib.metadata
import platform
from types import SimpleNamespace


def python_version():
    return platform.python_version()


def module_version(name):
    try:
        module = importlib.import_module(name)
    except Exception as error:
        return f"ERROR {type(error).__name__}: {error}"
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    try:
        return importlib.metadata.version(name)
    except Exception:
        return "available"


def opus_available():
    try:
        from LXST.Codecs.libs.pyogg.opus import PYOGG_OPUS_AVAIL

        return bool(PYOGG_OPUS_AVAIL), "available" if PYOGG_OPUS_AVAIL else "libopus not loaded"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def codec2_available():
    try:
        import pycodec2

        codec_class = getattr(pycodec2, "Codec2")
        codec = codec_class(3200)
        return True, f"mode 3200, {codec.samples_per_frame()} samples/frame"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def collect_versions():
    return {
        "python": python_version(),
        "kivy": module_version("kivy"),
        "rns": module_version("RNS"),
        "lxst": module_version("LXST"),
        "numpy": module_version("numpy"),
        "opus": opus_available()[1],
        "codec2": codec2_available()[1],
    }


def _attach(codec, source, sink):
    setattr(codec, "source", source)
    setattr(codec, "sink", sink)


def _tone(milliseconds, samplerate=48000, frequency=440.0, amplitude=0.1):
    import numpy as np

    count = int(samplerate * milliseconds / 1000)
    time = np.arange(count, dtype="float32") / samplerate
    return (amplitude * np.sin(2.0 * np.pi * frequency * time)).astype("float32").reshape(-1, 1)


def codec_roundtrip():
    import numpy as np
    from LXST.Codecs import Codec2, Opus

    source = SimpleNamespace(samplerate=48000, channels=1)
    sink = SimpleNamespace(samplerate=48000, channels=1)
    results = []

    opus_profiles = (
        ("opus-high", Opus.PROFILE_VOICE_HIGH, 20),
        ("opus-med", Opus.PROFILE_VOICE_MEDIUM, 60),
        ("opus-low", Opus.PROFILE_VOICE_LOW, 60),
    )
    for name, profile, milliseconds in opus_profiles:
        try:
            codec = Opus(profile)
            _attach(codec, source, sink)
            encoded = codec.encode(_tone(milliseconds))
            decoded = codec.decode(encoded)
            results.append(
                {
                    "codec": name,
                    "encoded_bytes": len(encoded),
                    "decoded_samples": int(np.asarray(decoded).size),
                    "ok": len(encoded) > 0 and np.asarray(decoded).size > 0,
                }
            )
        except Exception as error:
            results.append({"codec": name, "ok": False, "error": f"{type(error).__name__}: {error}"})

    codec2_modes = (
        ("c2-3200", Codec2.CODEC2_3200, 200),
        ("c2-2400", Codec2.CODEC2_2400, 200),
        ("c2-1200", Codec2.CODEC2_1200, 400),
    )
    for name, mode, milliseconds in codec2_modes:
        try:
            codec = Codec2(mode)
            _attach(codec, source, sink)
            encoded = codec.encode(_tone(milliseconds))
            decoded = codec.decode(encoded)
            results.append(
                {
                    "codec": name,
                    "encoded_bytes": len(encoded),
                    "decoded_samples": int(np.asarray(decoded).size),
                    "ok": len(encoded) > 1 and np.asarray(decoded).size > 0,
                }
            )
        except Exception as error:
            results.append({"codec": name, "ok": False, "error": f"{type(error).__name__}: {error}"})

    return results


def format_versions():
    return "\n".join(f"{name}: {value}" for name, value in collect_versions().items())


def audio_sanity(seconds=0.8):
    import time

    from LXST.Codecs import Opus
    from LXST.Sinks import LineSink
    from LXST.Sources import LineSource

    results = []
    source = None
    try:
        source = LineSource(target_frame_ms=20, codec=Opus(Opus.PROFILE_VOICE_HIGH))
        source.start()
        time.sleep(seconds)
        results.append({"device": "capture", "ok": bool(source.should_run), "samplerate": source.samplerate})
    except Exception as error:
        results.append({"device": "capture", "ok": False, "error": f"{type(error).__name__}: {error}"})
    finally:
        if source is not None:
            source.stop()
            time.sleep(0.2)

    sink = None
    try:
        import numpy as np

        sink = LineSink()
        frame = _tone(20, amplitude=0.05)
        if sink.channels > 1:
            frame = np.repeat(frame, sink.channels, axis=1)
        deadline = time.time() + seconds
        while time.time() < deadline:
            sink.handle_frame(frame)
            time.sleep(0.02)
        results.append(
            {
                "device": "playback",
                "ok": bool(sink.should_run),
                "samplerate": sink.backend.samplerate,
                "frames": sink.samples_per_frame,
            }
        )
    except Exception as error:
        results.append({"device": "playback", "ok": False, "error": f"{type(error).__name__}: {error}"})
    finally:
        if sink is not None:
            sink.stop()
            time.sleep(0.2)

    return results
