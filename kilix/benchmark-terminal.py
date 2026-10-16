#!/usr/bin/env python3
"""Measure decoder-to-PTY throughput; validate and hash every RGB wire frame.

This is a transport benchmark, not a display refresh-rate measurement. Run the
same fixture directory against both binaries; compare pixel hashes separately
from elapsed time. Old mpv's trailing base64 NUL is recorded and tolerated only
for baseline comparisons. No input, terminal, or live session is reused.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import resource
import select
import struct
import subprocess
import tempfile
import termios
import time
import zlib


class Capture:
    def __init__(self):
        self.pending = b''
        self.payload = bytearray()
        self.headers = None
        self.frames = 0
        self.wire_bytes = 0
        self.nul_frames = 0
        self.digests = []
        self.compressed = 0
        self.ids = set()
        self.live = set()
        self.max_live = 0
        self.global_deletes = 0
        self.first_frame = None
        self.dimensions = []

    def feed(self, chunk):
        self.wire_bytes += len(chunk)
        self.pending += chunk
        while True:
            start = self.pending.find(b'\x1b_G')
            if start < 0:
                self.pending = self.pending[-2:]
                return
            end = self.pending.find(b'\x1b\\', start + 3)
            if end < 0:
                self.pending = self.pending[start:]
                return
            packet = self.pending[start+3:end]
            self.pending = self.pending[end+2:]
            control, _, data = packet.partition(b';')
            fields = dict(pair.split(b'=', 1) for pair in control.split(b',') if b'=' in pair)
            if fields.get(b'a') == b'd':
                if b'i' in fields:
                    self.live.discard(int(fields[b'i']))
                else:
                    self.global_deletes += 1
                    self.live.clear()
                continue
            if fields.get(b'a') in (b'T', b't'):
                assert self.headers is None, 'unterminated frame'
                self.headers = fields
            if self.headers is None:
                continue
            self.payload.extend(data)
            if fields.get(b'm', b'0') == b'0':
                encoded = bytes(self.payload)
                if encoded.endswith(b'\0'):
                    self.nul_frames += 1
                    encoded = encoded[:-1]
                raw = base64.b64decode(encoded, validate=True)
                if self.headers.get(b't') == b's':
                    name = raw.decode('ascii')
                    assert name.startswith('kilix-mpv-') and '/' not in name
                    path = Path('/dev/shm') / name
                    raw = path.read_bytes()
                    path.unlink()  # terminal acknowledgment; allow slot reuse
                if self.headers.get(b'o') == b'z':
                    raw = zlib.decompress(raw)
                    self.compressed += 1
                width, height = int(self.headers[b's']), int(self.headers[b'v'])
                self.dimensions.append((width, height))
                assert len(raw) == width * height * 3, (len(raw), width, height)
                ident = int(self.headers.get(b'i', b'0'))
                self.ids.add(ident)
                if ident:
                    self.live.add(ident)
                    self.max_live = max(self.max_live, len(self.live))
                self.digests.append(hashlib.sha256(raw).hexdigest())
                self.frames += 1
                self.first_frame = self.first_frame or time.monotonic()
                self.payload.clear()
                self.headers = None


def run(player, clip, width, height, frames, extra):
    capture = Capture()
    with tempfile.TemporaryDirectory(prefix='kilix-mpv-bench-') as home:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, width, height))
        start = time.monotonic()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        process = subprocess.Popen(
            [player, '--no-config', '--load-scripts=no', '--vo=kitty', '--audio=no',
             '--osd-level=0', '--osc=no', '--untimed', '--framedrop=no',
             '--frames=' + str(frames), '--really-quiet', *extra, str(clip)],
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
            env={'HOME': home, 'PATH': os.environ['PATH'], 'TERM': 'xterm-kitty'})
        os.close(slave)
        try:
            while time.monotonic() - start < 90:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    capture.feed(chunk)
                elif process.poll() is not None:
                    break
            process.wait(timeout=2)
            assert process.returncode == 0, process.returncode
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
        elapsed = time.monotonic() - start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert frames <= capture.frames <= frames + 5, (capture.frames, frames)
    unique_sequence = [h for i, h in enumerate(capture.digests) if not i or h != capture.digests[i-1]]
    return dict(frames=capture.frames, bytes=capture.wire_bytes,
                seconds=elapsed, transport_fps=capture.frames/elapsed,
                cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                first_frame_seconds=capture.first_frame-start,
                trailing_nul_frames=capture.nul_frames, compressed_frames=capture.compressed,
                image_ids=sorted(capture.ids), max_live_named_images=capture.max_live,
                live_images_at_exit=len(capture.live), global_deletes=capture.global_deletes,
                pixels_sha256=hashlib.sha256(''.join(unique_sequence).encode()).hexdigest(),
                pixel_hashes=unique_sequence)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('player')
    parser.add_argument('output', type=Path)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=60)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--player-option', action='append', default=[])
    parser.add_argument('--baseline', help='interleave an unmodified baseline; verify pixel equality')
    args = parser.parse_args()
    args.fixtures.mkdir(parents=True, exist_ok=True)
    results = []
    for scene, source in [('pattern', 'testsrc2=size=1280x720:rate=30'),
                          ('noise', 'testsrc2=size=1280x720:rate=30,noise=alls=50:allf=t:all_seed=7')]:
        clip = args.fixtures / (scene + '.mkv')
        if not clip.exists():
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', source,
                            '-frames:v', str(args.frames), '-c:v', 'ffv1', str(clip)], check=True)
        for width, height in [(640, 360), (1280, 720)]:
            for repeat in range(args.repeats):
                players = [('candidate', args.player, args.player_option)]
                if args.baseline:
                    players.append(('baseline', args.baseline, []))
                if repeat % 2:
                    players.reverse()
                pair = []
                for label, player, options in players:
                    result = run(str(Path(player).resolve()), clip, width, height, args.frames, options)
                    result.update(scene=scene, width=width, height=height, repeat=repeat, variant=label)
                    pair.append(result)
                    results.append(result)
                    args.output.write_text(json.dumps(results, indent=2) + '\n')
                    print(json.dumps({k:v for k,v in result.items() if k not in ('pixels_sha256','pixel_hashes','image_ids')}), flush=True)
                if args.baseline:
                    assert pair[0]['pixel_hashes'] == pair[1]['pixel_hashes'], 'RGB sequence changed'


if __name__ == '__main__':
    main()
