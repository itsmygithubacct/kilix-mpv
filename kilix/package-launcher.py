#!/usr/bin/env python3
"""Package the exact Kilix launcher revision, never a mutable checkout file."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root, work, package, output = map(Path, sys.argv[1:])
    pin = json.loads((root / 'kilix/LAUNCHER.json').read_text())
    revision = pin['commit']
    source = os.environ.get('KILIX_LAUNCHER_SOURCE')
    if source:
        source = Path(source).resolve()
    else:
        source = work / 'launcher-source'
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'fetch', '--depth=1',
                        pin['repository'], revision], check=True)
    resolved = subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', revision + '^{commit}'], text=True).strip()
    if resolved != revision:
        raise RuntimeError('launcher commit does not match pin')
    lib = package / 'usr/lib/kilix-mpv'
    doc = package / 'usr/share/doc/kilix-mpv'
    lib.mkdir(parents=True)
    for name, digest in pin['files'].items():
        data = subprocess.check_output(['git', '-C', str(source), 'show', revision + ':' + name])
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError('launcher checksum mismatch: ' + name)
        dest = doc / 'LICENSE.launcher' if name == 'LICENSE' else lib / Path(name).name
        dest.write_bytes(data)
        dest.chmod(0o644)
    command = package / 'usr/bin/kilix-video'
    command.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/lib/kilix-mpv/terminal_video.py "$@"\n')
    command.chmod(0o755)
    (doc / 'LAUNCHER.json').write_text(json.dumps(pin, indent=2) + '\n')
    archive = output / ('kilix-launcher_' + revision + '.source.tar.gz')
    with archive.open('wb') as stream:
        subprocess.run(['git', '-C', str(source), 'archive', '--format=tar.gz',
                        '--prefix=kilix-launcher-' + revision + '/', revision],
                       stdout=stream, check=True)


if __name__ == '__main__':
    main()
