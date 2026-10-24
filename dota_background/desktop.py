"""Launch our own Quickshell config as a normal application window."""
from pathlib import Path
import os
import shutil
import subprocess
import sys


def run():
    executable = shutil.which('quickshell') or shutil.which('qs')
    if not executable:
        from .gtk_gui import run as fallback
        return fallback()
    project = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env['DOTA_BACKGROUND_PYTHON'] = sys.executable
    env['DOTA_BACKGROUND_PROJECT'] = str(project)
    result = subprocess.run([executable, '-n', '-p', str(project / 'qml/shell.qml')], cwd=project, env=env)
    if result.returncode:
        raise ValueError('Quickshell завершился с ошибкой. Подробности приведены выше.')
