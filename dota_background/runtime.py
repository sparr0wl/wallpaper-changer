"""Runtime paths and process options shared by source and installed builds."""
from pathlib import Path
import os
import subprocess


RELEASE_TAG = '7.41f+Trove_of_Terror'


def data_directory():
    if os.environ.get('DOTA_BACKGROUND_STORAGE'):
        return Path(os.environ['DOTA_BACKGROUND_STORAGE']).expanduser()
    legacy = Path.home() / '.local/share/dota-background-changer'
    if os.name == 'nt' and not legacy.exists():
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'WallpaperChanger'
    return legacy


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def steam_roots():
    home = Path.home()
    roots = [home / '.local/share/Steam', home / '.steam/steam',
             home / '.var/app/com.valvesoftware.Steam/.local/share/Steam',
             home / 'Library/Application Support/Steam']
    for variable in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / 'Steam')
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                roots.append(Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
        except OSError:
            pass
    return roots
