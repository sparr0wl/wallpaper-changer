"""Line-oriented JSON backend for the standalone Quickshell window."""
from pathlib import Path
import json
import os
import re
import shutil
import sys
import traceback

from . import core, media, mounts
from .library import Fonts, Library, read_json, write_json


def palette():
    result = {'background': '#101114', 'surface': '#191b20', 'raised': '#22252b',
              'foreground': '#e6e8ef', 'muted': '#8c929f', 'accent': '#a9b8d0', 'border': '#353841',
              'font': 'Noto Sans', 'name': '', 'omarchy': False}
    root = Path.home() / '.local/state/omarchy/current'
    path = root / 'theme/colors.toml'
    if not shutil.which('omarchy') or not (root / 'theme.name').is_file():
        return result
    try:
        import tomllib
        values = tomllib.loads(path.read_text())
        mapping = {'background': 'background', 'foreground': 'foreground', 'muted': 'muted',
                   'accent': 'accent', 'lighter_background': 'raised', 'dark_background': 'surface', 'selection': 'border'}
        for source, target in mapping.items():
            value = values.get(source, '')
            if re.fullmatch(r'#[a-fA-F0-9]{6}', value):
                result[target] = value
        result['name'] = (root / 'theme.name').read_text().strip().replace('-', ' ').title()
        result['omarchy'] = True
    except (OSError, ValueError, ImportError):
        pass
    return result


def snapshot(library):
    active, fix = library.active()
    screens = media.monitors()
    mounted_folder, mounted = mounts.installation(library.game) if library.game else (None, None)
    from .steam_options import obsolete_options
    return {'items': library.items(), 'active': active or '', 'game': str(library.game or ''),
            'template': str(library.template), 'scene_fix': fix, 'palette': palette(), 'monitors': screens,
            'resolution': list(library.dimensions()), 'fonts': Fonts(library.game, library.storage).catalog() if library.game else [],
            'resolution_fixed': bool(library.settings.get('resolution')),
            'game_installed': bool(mounted or (library.game and (library.game / 'dota_123').is_dir())),
            'mount_ready': bool(mounted), 'mount_folder': str(mounted_folder or ''),
            'obsolete_launch_option': bool(obsolete_options()),
            'language': mounts.language_status(library.game) if library.game else {},
            'scene_needs_update': scene_needs_update(library, fix),
            'launch_option': ''}


def scene_needs_update(library, fix):
    if not library.game:
        return False
    path = library.game / 'dota/pak01_dir.vpk'
    if not path.is_file():
        return True
    stat = path.stat()
    return not fix or fix.get('archive_size') != stat.st_size or fix.get('archive_mtime_ns') != stat.st_mtime_ns


def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def serve():
    # One backend owns mutations; a second app cannot race install/font actions.
    import fcntl
    import signal
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    storage = Path(os.environ.get('DOTA_BACKGROUND_STORAGE', Path.home() / '.local/share/dota-background-changer'))
    storage.mkdir(parents=True, exist_ok=True)
    with (storage / '.app.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit({'type': 'error', 'message': 'Приложение уже открыто. Используйте существующее окно.'})
            return 1
        library = Library(storage)
        emit({'type': 'progress', 'percent': 0, 'message': 'Загрузка библиотеки и превью…'})
        try:
            library.migrate()
        except Exception as e:
            emit({'type': 'notice', 'message': 'Не все старые фоны удалось импортировать: ' + str(e)})
        emit({'type': 'state', 'state': snapshot(library)})
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                action = request.get('action')
                message = ''
                progress = lambda percent, text: emit({'type': 'progress', 'percent': percent, 'message': text})
                if action == 'state':
                    pass
                elif action == 'add':
                    progress(0, 'Добавление видео в библиотеку')
                    identifier = library.import_video(request['path'])
                    # User only chooses a video; convert, fix and apply automatically.
                    library.activate(identifier, request.get('size'), progress)
                    message = 'Фон установлен в штатную языковую папку. Перезапустите Dota 2. Параметр -language 123 не нужен.'
                elif action == 'activate':
                    library.activate(request['id'], request.get('size'), progress)
                    message = 'Фон установлен. Перезапустите Dota 2.'
                elif action == 'repair':
                    progress(10, 'Обновление фикса события из установленных файлов Dota 2')
                    result = library.repair_scene()
                    message = 'Фикс обновлён: ' + result['scene_fix']['event_scene'] + '. Проверьте фон после запуска игры.'
                elif action == 'disable':
                    mounts.disable(library.game)
                    message = 'Фон отключён; прежний аудиоязык восстановлен. Старый параметр -language 123 больше не нужен.'
                elif action == 'font':
                    if not isinstance(request.get('enabled'), bool):
                        raise ValueError('Нужно логическое состояние шрифта')
                    Fonts(library.game, library.storage).toggle(request['name'], request['enabled'])
                    message = 'Шрифт ' + ('включён' if request['enabled'] else 'отключён') + '. Перезапустите Dota 2.'
                elif action == 'settings':
                    if request.get('game'):
                        library.game = core.game_directory(request['game'])
                        library.settings['game'] = str(library.game)
                    if request.get('template'):
                        core.load_template(request['template'])
                        library.template = Path(request['template']).expanduser().resolve()
                        library.settings['template'] = str(library.template)
                    if 'resolution' in request:
                        library.settings['resolution'] = list(media.valid_size(request['resolution'])) if request['resolution'] else None
                    write_json(library.config_path, library.settings)
                    message = 'Настройки сохранены.'
                elif action == 'rescan':
                    library.migrate()
                    message = 'Библиотека обновлена.'
                else:
                    raise ValueError('Неизвестная команда')
                emit({'type': 'state', 'state': snapshot(library), 'message': message, 'action': action})
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                emit({'type': 'error', 'message': str(e), 'action': request.get('action')})
                try:
                    emit({'type': 'state', 'state': snapshot(library), 'action': request.get('action')})
                except Exception:
                    pass
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(serve())
    except KeyboardInterrupt:
        raise SystemExit(130)
