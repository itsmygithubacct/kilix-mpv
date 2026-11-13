#!/usr/bin/env python3
"""Keep decoded formats through to the terminal scaler, with both transports."""
import importlib.util
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time

spec = importlib.util.spec_from_file_location('protocol', Path(__file__).with_name('test-protocol.py'))
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


def check_rgb_positions(player, root):
    """RGB samples are co-located; guessed YUV locations must not shift them."""
    flags = 'lanczos+accurate_rnd+full_chroma_int+full_chroma_inp'
    for fmt in ('yuv420p', 'yuv422p', 'yuv444p', 'rgb24'):
        for location in ('left', 'center'):
            clip = root / f'positions-{fmt}-{location}.nut'
            codec = (['-c:v', 'rawvideo'] if fmt == 'rgb24' else
                     ['-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast',
                      '-x264-params', 'chromaloc=' + ('0' if location == 'left' else '1')])
            subprocess.run([
                'ffmpeg', '-v', 'error', '-filter_threads', '1', '-f', 'lavfi',
                '-i', 'testsrc2=size=384x216:rate=30', '-frames:v', '2',
                *codec, '-threads', '1', '-pix_fmt', fmt,
                '-colorspace', 'bt709', '-chroma_sample_location', location, str(clip)], check=True)
            reference = subprocess.check_output([
                'ffmpeg', '-v', 'error', '-filter_threads', '1', '-i', str(clip),
                '-vf', f'scale=321:181:flags={flags}:in_chroma_loc={location}',
                '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
            expected = hashlib.sha256(reference).hexdigest()
            for shm in ('no', 'yes'):
                options = ['--pause', '--vo-kitty-width=321', '--vo-kitty-height=181',
                           '--keepaspect=no', '--sws-scaler=lanczos', '--sws-allow-zimg=no',
                           '--sws-fast=no', '--vo-kitty-use-shm=' + shm,
                           '--vf=format:chroma-location=' + ('mpeg2/4/h264' if location == 'left' else 'mpeg1/jpeg')]
                with protocol.Session(player, clip, root, options) as session:
                    session.wait(lambda: session.capture.frames > 0)
                    assert session.capture.digests[0] == expected, (fmt, location, shm, 'RGB position differs from FFmpeg')
                    time.sleep(.15)
            print('PASS RGB sample positions against FFmpeg:', fmt, location, flush=True)


def main():
    player = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix='mpv-yuv-') as directory:
        root = Path(directory)
        for fmt in ('yuv420p', 'yuv422p', 'yuv444p', 'yuv420p10le', 'nv12', 'rgb24'):
            clip = root / (fmt + '.nut')
            subprocess.run([
                'ffmpeg', '-v', 'error', '-filter_threads', '1', '-f', 'lavfi',
                '-i', 'testsrc2=size=384x216:rate=30', '-frames:v', '3',
                '-c:v', 'rawvideo', '-threads', '1', '-pix_fmt', fmt, str(clip)], check=True)
            for geometry in ([], ['--video-zoom=0.35', '--video-pan-x=0.1']):
                hashes = []
                for shm in ('no', 'yes'):
                    options = ['--pause', '--vo-kitty-width=321', '--vo-kitty-height=181',
                               '--vo-kitty-use-shm=' + shm, *geometry]
                    with protocol.Session(player, clip, root, options) as session:
                        session.wait(lambda: session.capture.frames > 0)
                        params = session.command('get_property', 'video-out-params')
                        expected = 'yuv420p10' if fmt == 'yuv420p10le' else fmt
                        assert params['pixelformat'] == expected, (fmt, params)
                        hashes.append(session.capture.digests[0])
                        assert session.capture.dimensions[0] == (321, 181), session.capture.dimensions
                        # Drain the initial paused redraw before quit unlinks
                        # the shared-memory slots the PTY reader acknowledges.
                        time.sleep(.15)
                        if session.error:
                            raise session.error
                    assert session.capture.live == set(), 'image survives player exit'
                assert hashes[0] == hashes[1], (fmt, geometry, 'transport changed pixels')
            print('PASS native format, scaling, crop and both transports:', fmt, flush=True)
        check_rgb_positions(player, root)


if __name__ == '__main__':
    main()
