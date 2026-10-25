#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --parallel 4
cmake --install build/native --prefix "$HOME/.local/opt/wallpaper-changer"
mkdir -p "$HOME/.local/bin"
ln -sfn "$HOME/.local/opt/wallpaper-changer/bin/wallpaper-changer" "$HOME/.local/bin/wallpaper-changer"
./install-desktop.sh
"$HOME/.local/bin/wallpaper-changer" --version
