#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
/usr/bin/python3 - <<'PY'
from pathlib import Path
project = Path.cwd()
entry = Path.home() / '.local/share/applications/wallpaper-changer.desktop'
if entry.exists() and 'X-DotaStudio=true' not in entry.read_text():
    raise SystemExit('Существующий сторонний ярлык не изменён: ' + str(entry))
entry.parent.mkdir(parents=True, exist_ok=True)
installed = Path.home() / '.local/bin/wallpaper-changer'
executable = str(installed if installed.is_file() else project / 'build/native/wallpaper-changer')
if not Path(executable).is_file():
    raise SystemExit('Сначала выполните ./install-user.sh')
for character in ('\\', '"', '`', '$'):
    executable = executable.replace(character, '\\' + character)
entry.write_text('[Desktop Entry]\nVersion=1.0\nType=Application\nName=Wallpaper changer\n'
                 'Comment=Video backgrounds and fonts for Dota 2\n'
                 'Comment[ru]=Видеофоны и шрифты Dota 2\n'
                 f'Exec="{executable}"\nIcon=preferences-desktop-wallpaper\n'
                 'Terminal=false\nCategories=Game;\nStartupNotify=true\nX-DotaStudio=true\n')
print('Ярлык установлен:', entry)
legacy = entry.with_name('dota-studio.desktop')
if legacy.is_file() and 'X-DotaStudio=true' in legacy.read_text():
    import shutil
    backup = Path.home() / '.local/share/dota-background-changer/launcher-backups'
    backup.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    shutil.move(str(legacy), str(backup / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-dota-studio.desktop')))
PY
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$HOME/.local/share/applications"
fi
