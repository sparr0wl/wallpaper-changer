#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
destination="$HOME/.local/opt/wallpaper-changer"
if [[ ! -x "$source_dir/bin/wallpaper-changer" || ! -d "$source_dir/lib/wallpaper-changer" ]]; then
    echo 'Extract the complete Linux archive before running install.sh.' >&2
    exit 1
fi
mkdir -p "$HOME/.local/opt" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
if [[ -e "$destination" ]]; then
    if [[ ! -f "$destination/lib/wallpaper-changer/dota_background/__init__.py" ]]; then
        echo "Unrecognized existing directory: $destination" >&2
        exit 1
    fi
    backups="$HOME/.local/share/dota-background-changer/install-backups"
    mkdir -p "$backups"
    mv -- "$destination" "$backups/$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$destination"
cp -a "$source_dir/bin" "$source_dir/lib" "$source_dir/share" "$destination/"
ln -sfn "$destination/bin/wallpaper-changer" "$HOME/.local/bin/wallpaper-changer"
WALLPAPER_INSTALLED_EXECUTABLE="$HOME/.local/bin/wallpaper-changer" python3 - <<'PY'
import os
from pathlib import Path
entry = Path.home() / '.local/share/applications/wallpaper-changer.desktop'
executable = os.environ['WALLPAPER_INSTALLED_EXECUTABLE'].replace('\\', '\\\\').replace('"', '\\"')
entry.write_text('[Desktop Entry]\nType=Application\nName=Wallpaper changer\n'
                 f'Exec="{executable}"\nIcon=wallpaper-changer\nTerminal=false\nCategories=Game;\nX-DotaStudio=true\n')
PY
cp "$destination/share/icons/hicolor/scalable/apps/wallpaper-changer.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/"
if command -v update-desktop-database >/dev/null; then update-desktop-database "$HOME/.local/share/applications"; fi
"$HOME/.local/bin/wallpaper-changer" --version
echo 'Installed. Launch wallpaper-changer or choose Wallpaper changer in Applications.'
