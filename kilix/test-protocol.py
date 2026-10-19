#!/usr/bin/env python3
"""Exercise protocol boundaries and actual input actions through isolated PTYs."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).with_name('benchmark-terminal.py'))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class Session:
    def __init__(self, player, clip, root, options=(), acknowledge_shm=True):
        self.master, self.slave = pty.openpty()
        self.original = termios.tcgetattr(self.slave)
        self.resize(1200, 720)
        self.ipc = root / 'ipc.sock'
        self.ipc.unlink(missing_ok=True)
        self.capture = benchmark.Capture(acknowledge_shm=acknowledge_shm)
        self.error = None
        self.tail = b''
        self.process = subprocess.Popen([
            player, '--no-config', '--load-scripts=no', '--vo=kitty', '--audio=no',
            '--osd-level=0', '--osc=no', '--really-quiet', '--loop-file=inf',
            '--input-ipc-server=' + str(self.ipc), *options, str(clip)],
            stdin=self.slave, stdout=self.slave, stderr=self.slave, start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
            env={'HOME': str(root), 'PATH': os.environ['PATH'], 'TERM': 'xterm-kitty'})
        self.stop = threading.Event()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        try:
            while not self.stop.is_set():
                if select.select([self.master], [], [], .05)[0]:
                    data = os.read(self.master, 65536)
                    self.tail = (self.tail + data)[-4096:]
                    if self.capture:
                        self.capture.feed(data)
        except BaseException as error:
            self.error = error

    def resize(self, width, height):
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 300, width, height))

    def command(self, *items):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(self.ipc))
            connection.sendall(json.dumps({'command': items, 'request_id': 1}).encode() + b'\n')
            with connection.makefile('rb') as stream:
                for line in stream:
                    reply = json.loads(line)
                    if reply.get('request_id') == 1:
                        assert reply['error'] == 'success', reply
                        return reply.get('data')
        raise RuntimeError('IPC closed')

    def wait(self, predicate):
        until = time.monotonic() + 6
        while time.monotonic() < until:
            if self.error:
                raise self.error
            if predicate():
                return
            assert self.process.poll() is None, self.process.returncode
            time.sleep(.03)
        raise AssertionError('condition did not become true')

    def __enter__(self):
        self.wait(self.ipc.exists)
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if self.process.poll() is None:
                self.command('quit')
                self.process.wait(timeout=5)
            time.sleep(.1)
            assert self.process.returncode == 0, self.process.returncode
            assert termios.tcgetattr(self.slave) == self.original, 'tty not restored'
            assert b'\x1b[?1006l' in self.tail and b'\x1b[?2026l' in self.tail
            assert not list(Path('/dev/shm').glob(f'kilix-mpv-{self.process.pid}-*'))
            if self.error:
                raise self.error
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.stop.set()
            self.reader.join(timeout=3)
            os.close(self.master)
            os.close(self.slave)


def main():
    player = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix='kilix-mpv-protocol-') as directory:
        root = Path(directory)
        clip = root / 'clip.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=128x72:rate=30', '-t', '2', '-c:v', 'ffv1', str(clip)], check=True)
        for compression in (0, 1):
            result = benchmark.run(player, clip, 16, 16, 2,
                                   ['--vo-kitty-compression=' + str(compression)])
            assert result['trailing_nul_frames'] == 0
            assert result['live_images_at_exit'] == 0
            assert result['clears_outside_sync'] == 0, 'screen cleared before replacement'
        print('PASS tiny single-packet frames: raw and compressed', flush=True)

        bindings = root / 'input.conf'
        bindings.write_text('MBTN_LEFT set pause no\nWHEEL_DOWN set mute yes\nCtrl+MBTN_LEFT set pause yes\nESC set volume 42\n')
        with Session(player, clip, root, ['--pause', '--input-conf=' + str(bindings)]) as session:
            session.wait(lambda: session.capture.frames > 0)
            first_image = session.capture.digests[0]
            os.write(session.master, b'\x1b[<35;29')
            time.sleep(.05)
            os.write(session.master, b'0;20M')
            session.wait(lambda: session.command('get_property', 'mouse-pos')['x'] > 1100)
            os.write(session.master, b'\x1b[<0;290;20M\x1b[<0;290;20m')
            session.wait(lambda: not session.command('get_property', 'pause'))
            os.write(session.master, b'\x1b[<65;290;20M')
            session.wait(lambda: session.command('get_property', 'mute'))
            os.write(session.master, b'\x1b[<16;290;20M\x1b[<16;290;20m')
            session.wait(lambda: session.command('get_property', 'pause'))
            # Invalid numeric fields must not turn into key presses or poison the next packet.
            os.write(session.master, b'\x1b[<0;999999999999999999;1M\x1b[<35;280;20M')
            session.wait(lambda: 1100 < session.command('get_property', 'mouse-pos')['x'] < 1140)
            os.write(session.master, b'\x1b')
            session.wait(lambda: session.command('get_property', 'volume') == 42)
            # A fragmented DECRQM reply enables precise pixel coordinates.
            os.write(session.master, b'\x1b[?1016;')
            time.sleep(.03)
            os.write(session.master, b'1$y\x1b[<35;777;360M')
            session.wait(lambda: session.command('get_property', 'mouse-pos')['x'] == 777)
            os.write(session.master, b'\x1b[<35;0;0M')
            session.wait(lambda: session.command('get_property', 'mouse-pos')['x'] == 0)
            # Unsupported mode reply falls back to cells without swallowing keys.
            os.write(session.master, b'\x1b[?1016;0$y\x1b[<35;290;20M')
            session.wait(lambda: session.command('get_property', 'mouse-pos')['x'] > 1100)
            for width, height in [(320, 180), (640, 360), (480, 270), (160, 90)] * 3:
                session.resize(width, height)
                session.wait(lambda: session.capture.dimensions[-1] == (width, height))
            session.resize(0, 0)
            session.wait(lambda: session.capture.dimensions[-1] == (1280, 720))
            assert session.capture.max_live <= 2 and session.capture.global_deletes == 0
            assert session.capture.clears_outside_sync == 0, 'resize cleared visible frame early'
        print('PASS fragmented/wide SGR motion, click, wheel, Ctrl-click, malformed recovery; 12 paused resizes; missing pixel geometry', flush=True)

        with Session(player, clip, root, ['--vo-kitty-use-shm=yes']) as session:
            session.wait(lambda: session.capture.frames >= 20)
            session.command('set_property', 'pause', True)
            time.sleep(.2)
            assert session.capture.digests[0] == first_image, 'SHM pixels differ from inline'
            assert session.capture.max_live <= 2
        print('PASS shared-memory acknowledgment/reuse and exact inline pixel equality', flush=True)

        # No terminal acknowledgment: the producer must cap outstanding objects at three.
        with Session(player, clip, root, ['--vo-kitty-use-shm=yes'], acknowledge_shm=False) as session:
            paths = lambda: list(Path('/dev/shm').glob(f'kilix-mpv-{session.process.pid}-*'))
            # shm_open exposes the name before ftruncate/memcpy complete. Only
            # the graphics command publishes a frame as ready for the reader.
            session.wait(lambda: session.capture.frames == 3)
            assert len(paths()) == 3
            first = {p.name: p.read_bytes() for p in paths()}
            session.resize(640, 360)
            time.sleep(.4)
            assert {p.name: p.read_bytes() for p in paths()} == first, 'unread frames overwritten'
            assert session.capture.frames == 3, 'published beyond the unread ring'
        print('PASS shared-memory backpressure: three immutable slots, resize, exit cleanup', flush=True)


if __name__ == '__main__':
    main()
