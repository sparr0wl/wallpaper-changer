"""Exercise the packaged Qt UI without changing game files or launching Steam."""
from pathlib import Path
import base64
import json
import os
import subprocess
import sys
import tempfile

project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project))
artifacts = project / '.artifacts'
artifacts.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='wallpaper-ui-') as temporary:
    root = Path(temporary)
    runtime = root / 'runtime'
    runtime.mkdir(mode=0o700)
    poster = root / 'preview.png'
    poster.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
    state = {'items': [{'id': str(i), 'title': 'Фон ' + str(i), 'preview_url': poster.as_uri(),
                       'video_url': '', 'media': {'width': 1920, 'height': 1080, 'duration': 15}} for i in range(3)],
             'fonts': [{'name': f'font-{i:02d}.otf', 'title': f'Шрифт {i}', 'enabled': True} for i in range(40)],
             'palette': {}, 'active': '0', 'resolution': [1920, 1080], 'monitors': []}
    state_path = root / 'state.json'
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    env = os.environ.copy()
    env.update({'QT_QPA_PLATFORM': 'offscreen', 'QT_QPA_PLATFORMTHEME': 'generic',
                'QT_QUICK_CONTROLS_STYLE': 'Basic', 'QT_QUICK_BACKEND': 'software', 'XDG_RUNTIME_DIR': str(runtime)})
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    binary = os.environ.get('WALLPAPER_CHANGER_BINARY', str(project / 'build/native/wallpaper-changer'))
    result = subprocess.run([binary, '--ui-test-state', str(state_path), '--ui-regression', '--smoke-test', str(artifacts)],
                            env=env, cwd=project, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    (artifacts / 'ui.log').write_text(output, encoding='utf-8')
    print(output)
    assert result.returncode == 0, result.returncode
    assert 'FONT_POSITION_PRESERVED' in output
    assert 'POLL_CONTENT_PRESERVED' in output
    for name in ('library', 'fonts', 'settings'):
        assert (artifacts / (name + '.png')).is_file(), name
    for line in output.splitlines():
        assert 'ReferenceError' not in line and 'TypeError' not in line and 'Unable to assign' not in line, line
    print('All three native Qt tabs rendered; polling and font state regressions passed.')
