#!/usr/bin/env python3
"""Check automatic audio output with a private ALSA device and no Pulse server."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import wave


def check_alsa_fallback(player, root):
    source = root / "stereo.wav"
    captured = root / "output.wav"
    config = root / "asound.conf"
    config.write_text(f'pcm.!default {{ type file slave.pcm {{ type null }} '
                      f'file "{captured}" format "wav" }}\n')
    # Put a square wave in the left channel and silence in the right.
    period = struct.pack("<hh", 8000, 0) * 48 + struct.pack("<hh", -8000, 0) * 48
    with wave.open(str(source), "wb") as audio:
        audio.setparams((2, 2, 48000, 0, "NONE", ""))
        audio.writeframes(period * 250)

    env = dict(os.environ, ALSA_CONFIG_PATH=str(config), XDG_RUNTIME_DIR=str(root),
               PULSE_SERVER="unix:" + str(root / "missing-pulse"))
    subprocess.run([player, "--no-config", "--no-terminal", "--no-video",
                    "--load-scripts=no", "--audio-channels=stereo", "--audio-format=s16",
                    str(source)], env=env, stdin=subprocess.DEVNULL, check=True, timeout=10)
    with wave.open(str(captured), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (2, 2, 48000)
        frames = audio.readframes(audio.getnframes())
    # Allow device padding while requiring a sustained run of the original samples.
    assert period * 100 in frames, "ALSA did not receive the stereo signal"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="kilix-mpv-audio-") as tmp:
        check_alsa_fallback(str(Path(sys.argv[1]).resolve()), Path(tmp))
    print("PASS automatic ALSA playback without a PulseAudio server")
