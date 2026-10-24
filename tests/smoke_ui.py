"""Render the actual app offscreen across all tabs, using the real backend."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dota_background.bridge import snapshot
from dota_background.library import Library

project = Path(__file__).resolve().parent.parent
artifacts = project / '.artifacts'
artifacts.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='dota-studio-ui-') as temporary:
    root = Path(temporary)
    runtime = root / 'runtime'
    runtime.mkdir(mode=0o700)
    shutil.copyfile(project / 'qml/ActionButton.qml', root / 'ActionButton.qml')
    source = (project / 'qml/shell.qml').read_text()
    # Snapshot real data, but never toggle actual game fonts from a UI test.
    state_path = root / 'state.json'
    state_path.write_text(json.dumps(snapshot(Library()), ensure_ascii=False))
    backend_path = root / 'backend.py'
    backend_path.write_text('''import json, sys
state = json.load(open(sys.argv[1]))
print(json.dumps({'type': 'state', 'state': state, 'message': 'Выбери фон или добавь своё видео'}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({'type': 'state', 'state': state, 'action': request.get('action')}), flush=True)
''')
    source = source.replace('command: [Quickshell.env("DOTA_BACKGROUND_PYTHON") || "/usr/bin/python3", "-m", "dota_background.bridge"]',
                            'command: ["/usr/bin/python3", ' + json.dumps(str(backend_path)) + ', ' + json.dumps(str(state_path)) + ']')
    capture = '''
    Timer {
        property int step: 0
        interval: 1400
        running: app.ready && !app.busy
        repeat: true
        onTriggered: {
            var pages = ["library", "fonts", "settings"];
            if (step >= pages.length) { Qt.quit(); return; }
            var name = pages[step];
            if (step === 0 && grid.count > 0) {
                grid.forceLayout();
                var card = grid.itemAtIndex(0);
                var selection = app.selected;
                app.send("state");
                if (app.busy || !app.polling) { console.error("POLL_SHOWED_PROGRESS"); Qt.quit(); return; }
                app.receive(JSON.stringify({type: "state", action: "state", state: JSON.parse(JSON.stringify(app.data))}));
                grid.forceLayout();
                if (app.busy || app.polling || grid.itemAtIndex(0) !== card || app.selected !== selection) {
                    console.error("POLL_RECREATED_CONTENT"); Qt.quit(); return;
                }
                // A font/theme-only refresh must also preserve library delegates.
                var refreshed = JSON.parse(JSON.stringify(app.data));
                refreshed.fonts[0].enabled = !refreshed.fonts[0].enabled;
                app.receive(JSON.stringify({type: "state", action: "state", state: refreshed}));
                grid.forceLayout();
                if (grid.itemAtIndex(0) !== card) { console.error("POLL_RECREATED_CARDS"); Qt.quit(); return; }
                console.log("POLL_CONTENT_PRESERVED");
            }
            if (step === 1 && fontsModel.count > 20) {
                fontList.positionViewAtIndex(20, ListView.Center);
                fontList.forceLayout();
                var before = fontList.contentY;
                var row = fontList.itemAtIndex(20);
                var state = JSON.parse(JSON.stringify(app.data));
                state.fonts[20].enabled = !state.fonts[20].enabled;
                app.receive(JSON.stringify({type: "state", state: state}));
                fontList.forceLayout();
                if (app.page !== "fonts" || Math.abs(fontList.contentY - before) > 0.5 || fontList.itemAtIndex(20) !== row) {
                    console.error("FONT_POSITION_LOST"); Qt.quit(); return;
                }
                console.log("FONT_POSITION_PRESERVED");
            }
            canvas.grabToImage(function(result) {
                result.saveToFile(Quickshell.env("DOTA_STUDIO_CAPTURE") + "/" + name + ".png");
                step++;
                if (step < pages.length) app.page = pages[step];
            });
        }
    }
'''
    position = source.rfind('}')
    (root / 'shell.qml').write_text(source[:position] + capture + source[position:])
    env = os.environ.copy()
    env.update({'QT_QPA_PLATFORM': 'offscreen', 'QT_QPA_PLATFORMTHEME': 'generic',
                'QT_QUICK_CONTROLS_STYLE': 'Basic', 'QT_QUICK_BACKEND': 'software',
                'XDG_RUNTIME_DIR': str(runtime), 'DOTA_BACKGROUND_PYTHON': '/usr/bin/python3',
                'DOTA_BACKGROUND_PROJECT': str(project), 'DOTA_STUDIO_CAPTURE': str(artifacts)})
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    result = subprocess.run(['quickshell', '-p', str(root / 'shell.qml')], env=env, cwd=project,
                            capture_output=True, text=True, timeout=45)
    output = result.stdout + result.stderr
    (artifacts / 'ui.log').write_text(output)
    print(output)
    assert result.returncode == 0, result.returncode
    assert 'FONT_POSITION_PRESERVED' in output, 'Font update did not preserve the visible row and scroll position'
    assert 'POLL_CONTENT_PRESERVED' in output, 'Background polling recreated cards or showed progress'
    for name in ('library', 'fonts', 'settings'):
        assert (artifacts / (name + '.png')).is_file(), name
    for line in output.splitlines():
        assert 'ReferenceError' not in line and 'TypeError' not in line and 'Unable to assign' not in line, line
    print('All three tabs rendered successfully.')
