#!/usr/bin/env python3
"""Private Xvfb/Kilix OSC controls, including button edges and fullscreen.

Requires Pillow, Xvfb, Openbox, xdotool, ImageMagick and a Lua-enabled player.
Pass --launcher to exercise the host supervisor as well as the player.
Screenshots are review evidence, not a physical-display performance test.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('player', type=Path)
    parser.add_argument('terminal', type=Path)
    parser.add_argument('clip', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--transport', choices=('inline', 'shm'), default='inline')
    parser.add_argument('--launcher', type=Path)
    parser.add_argument('--shm', action='store_true', help='alias for --transport shm')
    args = parser.parse_args()
    if args.shm:
        args.transport = 'shm'
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    player = args.player.resolve()
    engine = args.terminal.resolve()
    clip = args.clip.resolve()
    transport = args.transport
    private = root / transport
    private.mkdir(exist_ok=True)
    if (private / 'result.json').exists():
        raise RuntimeError('use a fresh output directory to preserve previous evidence')
    for name in ('home', 'config', 'cache', 'runtime', 'bin'):
        (private / name).mkdir(mode=0o700, exist_ok=True)
    ipc = private / 'mpv.sock'
    ipc.unlink(missing_ok=True)
    options = ['--input-ipc-server=' + str(ipc), '--pause', '--keep-open=yes',
               '--ao=null', '--osd-level=0',
               '--log-file=' + str(private / 'player.log')]
    shim = private / 'bin/kilix-mpv'
    shim.write_text('#!/usr/bin/python3\nimport os, sys\n'
                    f'player = {str(player)!r}\noptions = {options!r}\n'
                    'if \'--list-options\' in sys.argv: os.execv(player, [player] + sys.argv[1:])\n'
                    'os.execv(player, [player] + sys.argv[1:-2] + options + sys.argv[-2:])\n')
    shim.chmod(0o700)
    if args.launcher:
        launch = ['/usr/bin/python3', str(args.launcher.resolve()),
                  '--transport', transport, str(clip)]
    else:
        launch = [str(player), '--no-config', '--load-scripts=no', '--vo=kitty',
                  '--term-osd=no', '--term-status-msg=', '--vo-kitty-terminal-fullscreen=yes',
                  '--vo-kitty-use-shm=' + ('yes' if transport == 'shm' else 'no'),
                  *options, str(clip)]
    runner = private / 'run.py'
    runner.write_text('import subprocess, time\n'
                      f'p = subprocess.run({launch!r})\n'
                      'print("HOST_EXITED", p.returncode, flush=True)\ntime.sleep(30)\n')
    r, w = os.pipe()
    xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0',
                             '1280x900x24', '-nolisten', 'tcp'], pass_fds=[w],
                            stdout=subprocess.DEVNULL,
                            stderr=(private / 'xvfb.log').open('wb'))
    os.close(w)
    with os.fdopen(r) as display_pipe:
        display = ':' + display_pipe.readline().strip()
    env = {'HOME': str(private / 'home'), 'XDG_CONFIG_HOME': str(private / 'config'),
           'XDG_CACHE_HOME': str(private / 'cache'),
           'XDG_RUNTIME_DIR': str(private / 'runtime'),
           'PATH': str(private / 'bin') + ':/usr/bin:/bin', 'DISPLAY': display,
           'LANG': 'C.UTF-8', 'LIBGL_ALWAYS_SOFTWARE': '1',
           'KILIX_STORAGE_HOME': str(private / 'home/kilix')}
    wm = subprocess.Popen(['openbox', '--sm-disable'], env=env, stdout=subprocess.DEVNULL, stderr=(private/'wm.log').open('wb'))
    terminal = None
    connection = None
    replies = None
    try:
        terminal = subprocess.Popen([
            str(engine), '--config', 'NONE', '--class', 'kilix-errors-test',
            '-o', 'initial_window_width=900', '-o', 'initial_window_height=600',
            '-o', 'remember_window_size=no', '-o', 'allow_remote_control=yes', '-o', 'software_mouse_cursor=none',
            '-o', 'mouse_hide_wait=0', '/usr/bin/python3', str(runner)],
            env=env, stdout=subprocess.DEVNULL,
            stderr=(private / 'terminal.log').open('wb'), start_new_session=True)
        for _ in range(150):
            if ipc.exists(): break
            assert terminal.poll() is None
            time.sleep(.1)
        connection = socket.socket(socket.AF_UNIX)
        connection.settimeout(3)
        connection.connect(str(ipc))
        replies = connection.makefile('rb')
        request_id = 0

        def command(*items, allow_error=False):
            nonlocal request_id
            request_id += 1
            connection.sendall(json.dumps({'command': items, 'request_id': request_id})
                               .encode() + b'\n')
            for line in replies:
                reply = json.loads(line)
                if reply.get('request_id') == request_id:
                    assert allow_error or reply['error'] == 'success', reply
                    return reply.get('data')
            raise RuntimeError('IPC closed')
        def wait_for(predicate):
            deadline = time.monotonic() + 5
            while not predicate():
                if time.monotonic() >= deadline:
                    raise AssertionError('native input/state did not arrive within five seconds')
                time.sleep(.05)

        def xdo(*items): return subprocess.check_output(['xdotool', *items], env=env, text=True, timeout=5).strip()
        def screenshot(name):
            path=private/(name+'.png')
            subprocess.run(['import','-display',display,'-window','root',str(path)],env=env,check=True)
            return Image.open(path).convert('RGB')
        time.sleep(1)
        window=xdo('search','--class','kilix-errors-test').splitlines()[-1]
        xdo('windowsize',window,'900','600')
        xdo('windowmap',window)
        xdo('mousemove','990','690')
        time.sleep(1)
        print(xdo('getwindowgeometry',window),flush=True)
        print(command('get_property','osd-dimensions'),flush=True)
        before=screenshot('before')
        for _ in range(30):
            if before.getbbox(): break
            xdo('mousemove','--window',window,'450','300')
            time.sleep(.1)
            before=screenshot('before')
        assert before.getbbox(), 'initial video blank'
        results=[]
        def point(name, width, height):
            # Rendered bottom-bar layout: virtual 720-high canvas; video is
            # centered in whole terminal cells. Positions are button centers,
            # independent of mpv's reported mouse transform.
            d=command('get_property','osd-dimensions')
            vscale=d['h']/720
            # Locate the terminal's grid and cell-snapped graphics origin via
            # its tty dimensions; account for window grid rounding/padding.
            pid=command('get_property','pid')
            import fcntl, termios, struct
            fd=os.open(f'/proc/{pid}/fd/0',os.O_RDONLY|os.O_NOCTTY)
            rows,cols,pw,ph=struct.unpack('HHHH',fcntl.ioctl(fd,termios.TIOCGWINSZ,b'\0'*8));os.close(fd)
            cell_h=ph/rows;cell_w=pw/cols
            ox=round((width-pw)/2)+int((pw-d['w'])/2/cell_w)*cell_w
            oy=round((height-ph)/2)+int((ph-d['h'])/2/cell_h)*cell_h
            x={'play':20.5*vscale,'volume':d['w']-56.5*vscale,'fullscreen':d['w']-20.5*vscale,'seek':d['w']*.5}[name]
            d['target_x'], d['target_y'] = x, d['h']-15*vscale
            return round(ox+x),round(oy+d['h']-15*vscale),d
        def pointer_at(x, y):
            mouse = command('get_property', 'mouse-pos')
            # Window-grid centering can round the outside padding by one pixel.
            return abs(mouse['x']-x) <= 2 and abs(mouse['y']-y) <= 2

        def click(name,width,height,button='1'):
            x,y,d=point(name,width,height)
            xdo('mousemove','--window',window,str(x),str(y))
            wait_for(lambda: pointer_at(d['target_x'], d['target_y']))
            mouse=command('get_property','mouse-pos')
            xdo('click',button);time.sleep(.3)
            return dict(name=name,x=x,y=y,mouse=mouse,osd=d)
        for width,height in [(900,600),(700,500),(1100,720),(520,700)]:
            xdo('windowsize',window,str(width),str(height));time.sleep(.5)
            command('set_property','pause',True)
            command('set_property','mute',False)
            command('set_property','volume',60)
            record={'width':width,'height':height,'clicks':[]}
            record['clicks'].append(click('play',width,height))
            wait_for(lambda: command('get_property','pause') is False)
            record['clicks'].append(click('play',width,height))
            wait_for(lambda: command('get_property','pause') is True)
            record['clicks'].append(click('volume',width,height))
            wait_for(lambda: command('get_property','mute') is True)
            # Exercise points near all four edges *inside* the drawn speaker
            # button. Cell rounding can move these into an adjacent hitbox.
            cx,cy,d=point('volume',width,height)
            for dx,dy in [(0,-11),(0,11),(-10,0),(10,0)]:
                command('set_property','mute',False)
                x=round(cx+dx*d['h']/720);y=round(cy+dy*d['h']/720)
                xdo('mousemove','--window',window,str(x),str(y))
                wait_for(lambda: pointer_at(d['target_x']+x-cx,d['target_y']+y-cy))
                xdo('click','1');time.sleep(.2)
                wait_for(lambda: command('get_property','mute') is True)
            record['clicks'].append(click('volume',width,height,'5'))
            wait_for(lambda: command('get_property','volume') < 60)
            command('seek',1,'absolute+exact');time.sleep(.2)
            record['clicks'].append(click('seek',width,height))
            wait_for(lambda: command('get_property','time-pos') > 10)
            # Real drag events exercise press/motion/release, not IPC seeking.
            x,y,_=point('seek',width,height)
            xdo('mousemove','--window',window,str(x-40),str(y));time.sleep(.1)
            xdo('mousedown','1');time.sleep(.1)
            left=command('get_property','time-pos')
            xdo('mousemove','--window',window,str(x+40),str(y));time.sleep(.2)
            xdo('mouseup','1');time.sleep(.2)
            wait_for(lambda: command('get_property','time-pos') > left+1)
            screenshot(f'controls-{width}')
            results.append(record)
            print(json.dumps(record),flush=True)
        # Verify actual window-manager state, not just mpv's option value.
        click('fullscreen',520,700);time.sleep(.6)
        state=subprocess.check_output(['xprop','-id',window,'_NET_WM_STATE'],env=env,text=True)
        assert '_NET_WM_STATE_FULLSCREEN' in state,state
        geo=xdo('getwindowgeometry','--shell',window)
        geometry=dict(line.split('=',1) for line in geo.splitlines() if '=' in line)
        click('fullscreen',int(geometry['WIDTH']),int(geometry['HEIGHT']));time.sleep(.6)
        state=subprocess.check_output(['xprop','-id',window,'_NET_WM_STATE'],env=env,text=True)
        assert '_NET_WM_STATE_FULLSCREEN' not in state,state
        pid=command('get_property','pid')
        command('quit')
        time.sleep(.5)
        assert not list(Path('/dev/shm').glob(f'kilix-mpv-{pid}-*')), 'SHM leaked on exit'
        (private/'result.json').write_text(json.dumps({'pass':True,'cases':results,'fullscreen_roundtrip':True},indent=2)+'\n')
    finally:
        if replies is not None:
            replies.close()
        if connection is not None:
            connection.close()
        if terminal is not None and terminal.poll() is None:
            terminal.terminate()
            try: terminal.wait(timeout=5)
            except subprocess.TimeoutExpired: terminal.kill(); terminal.wait()
        wm.terminate();wm.wait(timeout=5)
        xvfb.terminate(); xvfb.wait(timeout=5)


if __name__ == '__main__':
    main()
