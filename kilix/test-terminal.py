#!/usr/bin/env python3
"""Exercise the actual decoder, terminal input, resize, and normal cleanup."""
import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time


def run(player, sample, home, renderer, action, *, use_config=False,
        expected_renderer=None):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 320, 192))
    proc = subprocess.Popen(
        [player, *([] if use_config else ['--no-config']), '--load-scripts=no',
         *([] if renderer is None else ['--vo=' + renderer]),
         '--audio=no', '--loop-file=inf', str(sample)],
        stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
        env={'HOME': str(home), 'PATH': os.environ['PATH'], 'TERM': 'xterm-kitty'})
    os.close(slave)
    start = time.monotonic()
    sent = quit_sent = graphics = False
    tail = b''
    try:
        while time.monotonic() - start < 8:
            elapsed = time.monotonic() - start
            if elapsed > 0.6 and not sent:
                if action == 'mouse':
                    os.write(master, b'\x1b[MC' + bytes([73, 54]) +
                             b'\x1b[M ' + bytes([73, 54]) + b'\x1b[M#' + bytes([73, 54]))
                elif action == 'resize':
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 26, 90, 360, 208))
                    os.killpg(proc.pid, signal.SIGWINCH)
                else:
                    os.write(master, b'\x1b[C')
                sent = True
            if elapsed > 1.5 and not quit_sent:
                os.write(master, b'q')
                quit_sent = True
            if select.select([master], [], [], 0.03)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                graphics |= b'\x1b_G' in tail[-4:] + chunk
                tail = (tail + chunk)[-16384:]
            if proc.poll() is not None:
                break
        proc.wait(timeout=2)
        assert proc.returncode == 0, (renderer, action, proc.returncode, repr(tail[-400:]))
        assert sent and quit_sent, (renderer, action, 'exited before interaction')
        expected = expected_renderer or renderer or 'kitty'
        assert graphics == (expected == 'kitty'), (expected, 'unexpected graphics output', graphics)
        print(f'PASS {renderer or "default"} (config={use_config}, expected={expected}): {action}, quit', flush=True)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)


if __name__ == '__main__':
    player = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix='kilix-mpv-test-') as directory:
        home = Path(directory)
        sample = home / 'sample with spaces.mp4'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc=size=128x96:rate=5', '-t', '12', '-c:v', 'mpeg4', str(sample)], check=True)
        for renderer in (None, 'kitty', 'tct'):
            for action in ('mouse', 'resize', 'seek'):
                run(player, sample, home, renderer, action)
        run(player, sample, home, None, 'seek', use_config=True)
        run(player, sample, home, 'null', 'seek')
        config = home / '.config' / 'mpv' / 'mpv.conf'
        config.parent.mkdir(parents=True)
        config.write_text('vo=null\n', encoding='utf-8')
        run(player, sample, home, None, 'seek', use_config=True, expected_renderer='null')
        run(player, sample, home, 'kitty', 'seek', use_config=True)
        run(player, sample, home, None, 'seek')
