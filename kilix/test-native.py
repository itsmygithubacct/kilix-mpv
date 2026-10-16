#!/usr/bin/env python3
"""Private Xvfb/Kilix check: real OSC clicks, resize, and shared-memory cleanup.

Requires Xvfb, xdotool, ImageMagick import, and a built Kitty/Kilix engine.
Screenshots are evidence for review; this is not a physical-display FPS test.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('player', type=Path)
    parser.add_argument('terminal', type=Path)
    parser.add_argument('clip', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--shm', action='store_true')
    args = parser.parse_args()
    private = args.output.resolve()
    private.mkdir(parents=True, exist_ok=True)
    for name in ('home', 'config', 'cache', 'runtime'):
        (private / name).mkdir(mode=0o700, exist_ok=True)
    read_fd, write_fd = os.pipe()
    xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                             '1000x700x24', '-nolisten', 'tcp'], pass_fds=[write_fd],
                            stdout=subprocess.DEVNULL, stderr=(private / 'xvfb.log').open('wb'))
    os.close(write_fd)
    display = ':' + os.read(read_fd, 64).decode().strip()
    os.close(read_fd)
    env = {'HOME': str(private / 'home'), 'XDG_CONFIG_HOME': str(private / 'config'),
           'XDG_CACHE_HOME': str(private / 'cache'), 'XDG_RUNTIME_DIR': str(private / 'runtime'),
           'PATH': '/usr/bin:/bin', 'DISPLAY': display, 'LANG': 'C.UTF-8',
           'LIBGL_ALWAYS_SOFTWARE': '1'}
    ipc = private / 'mpv.sock'
    ipc.unlink(missing_ok=True)
    terminal = None
    try:
        terminal = subprocess.Popen([
            str(args.terminal.resolve()), '--config', 'NONE', '--class', 'kilix-mpv-quality-test',
            '-o', 'initial_window_width=900', '-o', 'initial_window_height=600',
            '-o', 'remember_window_size=no', '-o', 'software_mouse_cursor=none',
            '-o', 'mouse_hide_wait=0', str(args.player.resolve()), '--no-config',
            '--load-scripts=no', '--vo=kitty', '--term-osd=no', '--term-status-msg=',
            '--script-opts=osc-visibility=always', '--log-file=' + str(private / 'player.log'),
            '--mute=yes', '--pause', '--keep-open=yes', '--input-ipc-server=' + str(ipc),
            '--vo-kitty-use-shm=' + ('yes' if args.shm else 'no'), str(args.clip.resolve())],
            env=env, stdout=subprocess.DEVNULL, stderr=(private / 'kitty.log').open('wb'),
            start_new_session=True)
        for _ in range(150):
            if ipc.exists():
                break
            if terminal.poll() is not None:
                raise RuntimeError('terminal exited before IPC')
            time.sleep(.1)

        def command(*items):
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(3)
                connection.connect(str(ipc))
                connection.sendall(json.dumps({'command': items, 'request_id': 1}).encode() + b'\n')
                with connection.makefile('rb') as lines:
                    for line in lines:
                        reply = json.loads(line)
                        if reply.get('request_id') == 1:
                            assert reply['error'] == 'success', reply
                            return reply.get('data')
            raise RuntimeError('IPC closed without reply')

        def xdo(*items):
            return subprocess.check_output(['xdotool', *items], env=env, text=True).strip()

        time.sleep(1)
        window = xdo('search', '--class', 'kilix-mpv-quality-test').splitlines()[-1]
        results = []
        for width, height in [(900, 600), (700, 500)]:
            xdo('windowsize', window, str(width), str(height))
            # Motion requests an OSD refresh even while playback is paused.
            xdo('mousemove', '--window', window, str(width // 2), str(height // 2))
            time.sleep(.7)
            dimensions = command('get_property', 'osd-dimensions')
            mouse = command('get_property', 'mouse-pos')
            # Derive letterbox offset from mpv's actual coordinate transform.
            origin_y = height // 2 - mouse['y']
            seek_y = round(origin_y + dimensions['h'] - 4)
            xdo('mousemove', '--window', window, str(round(width * .5)), str(seek_y))
            command('seek', 0, 'absolute+exact')
            time.sleep(.3)
            before = command('get_property', 'time-pos')
            xdo('click', '1')
            time.sleep(.5)
            after = command('get_property', 'time-pos')
            print(json.dumps(dict(window=xdo('getwindowgeometry', window), dimensions=dimensions, mouse=mouse, seek_y=seek_y)), flush=True)
            subprocess.run(['import', '-display', display, '-window', 'root',
                            str(private / f'seek-{width}.png')], env=env, check=True)
            assert after > before + .2, (width, height, before, after, seek_y)
            results.append(dict(width=width, height=height, before=before, after=after,
                                mouse=command('get_property', 'mouse-pos'), osd=dimensions))
        pid = command('get_property', 'pid')
        command('quit')
        terminal.wait(timeout=10)
        assert not list(Path('/dev/shm').glob(f'kilix-mpv-{pid}-*')), 'shared-memory leak'
        (private / 'result.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps({'transport': 'shm' if args.shm else 'inline', 'checks': results}), flush=True)
    finally:
        if terminal is not None and terminal.poll() is None:
            terminal.terminate()
            try:
                terminal.wait(timeout=5)
            except subprocess.TimeoutExpired:
                terminal.kill()
                terminal.wait()
        xvfb.terminate()
        xvfb.wait(timeout=5)


if __name__ == '__main__':
    main()
