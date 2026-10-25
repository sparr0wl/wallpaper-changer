"""Launch the standard Qt application from source or an installation."""
from pathlib import Path
import os
import shutil
import subprocess
import sys


def run():
    project = Path(__file__).resolve().parent.parent
    suffix = '.exe' if os.name == 'nt' else ''
    candidates = [project / 'build/native' / ('wallpaper-changer' + suffix),
                  project / 'build/native/Release' / ('wallpaper-changer' + suffix)]
    executable = next((str(path) for path in candidates if path.is_file()), None)
    executable = executable or shutil.which('wallpaper-changer')
    if not executable:
        raise ValueError('Сначала соберите Qt-приложение: cmake -S . -B build/native && cmake --build build/native')
    env = os.environ.copy()
    env['WALLPAPER_CHANGER_PYTHON'] = sys.executable
    result = subprocess.run([executable], env=env)
    if result.returncode:
        raise ValueError('Wallpaper changer завершился с ошибкой. Подробности приведены выше.')
