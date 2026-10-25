"""Installed-package test. Works without Steam or a graphical session."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile

from .runtime import RELEASE_TAG, process_options
from .scene import lz4
from .vpk import VPK, write_vpk
from .media import convert


def main():
    for executable in ('ffmpeg', 'ffprobe'):
        if not shutil.which(executable):
            raise RuntimeError('Missing runtime tool: ' + executable)
    data = b'Wallpaper changer: compressed resource round trip' * 16
    assert lz4(lz4(data), len(data)) == data
    with tempfile.TemporaryDirectory(prefix='wallpaper-self-test-') as temporary:
        root = Path(temporary)
        write_vpk(root / 'test.vpk', {'test/data.txt': data})
        assert VPK(root / 'test.vpk').read('test/data.txt') == data
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=96x64:d=0.3',
                        '-c:v', 'mpeg4', str(root / 'input.mp4')], check=True, timeout=30, **process_options())
        result = convert(root / 'input.mp4', root / 'output.webm', (128, 72))
        assert (result['width'], result['height'], result['codec']) == (128, 72, 'vp9')
    print(json.dumps({'release': RELEASE_TAG, 'vpk': 'ok', 'lz4': 'ok', 'mp4_to_webm': 'ok'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
