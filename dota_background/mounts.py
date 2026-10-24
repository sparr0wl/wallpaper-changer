"""Install owned VPKs in a real audio-language search path (2026 layout)."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid

from . import core
from .vpk import VPK, write_vpk

MARKER = '.dota-studio-install.json'
LANGUAGES = ('russian', 'schinese', 'koreana')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.dota-studio-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def setting(text, key):
    matches = list(re.finditer(r'"' + re.escape(key) + r'"\s*"([^"\r\n]*)"', text, re.I))
    if len(matches) != 1:
        raise ValueError(f'В boot.vcfg ожидался один параметр {key}')
    return matches[0][1]


def set_audio(raw, language):
    text = raw.decode('utf-8-sig')
    setting(text, 'AudioLanguage')
    changed = re.sub(r'("AudioLanguage"\s*")[^"\r\n]*(")', lambda m: m[1] + language + m[2], text, count=1, flags=re.I)
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + changed.encode()


def installation(game, verify=False):
    game = core.game_directory(game)
    found = []
    for language in LANGUAGES:
        folder = game / ('dota_' + language)
        marker = folder / MARKER
        if marker.is_file():
            record = json.loads(marker.read_text())
            if record.get('app') != core.APP_ID:
                raise ValueError('Неизвестный владелец маркера Dota Studio')
            if verify:
                for name, checksum in record['owned_files'].items():
                    if not re.fullmatch(r'pak[0-9]{2}_dir\.vpk', name):
                        raise ValueError('Неверное имя установленного архива')
                    file = folder / name
                    if file.is_symlink() or not file.is_file() or digest(file) != checksum:
                        raise ValueError(f'Установленный пакет изменён: {name}')
            found.append((folder, record))
    if len(found) > 1:
        raise ValueError('Найдены две установки Dota Studio; требуется проверка вручную')
    return found[0] if found else (None, None)


def installed_package(game):
    folder, record = installation(game, verify=True)
    if record:
        package = Path(record['package'])
        core.check_package(package)
        return package
    legacy = core.game_directory(game) / 'dota_123'
    core.check_package(legacy)
    return legacy


def language_status(game):
    game = core.game_directory(game)
    path = game / 'dota/cfg/boot.vcfg'
    if not path.is_file():
        return {'audio': None, 'ui': None, 'folder': None}
    text = path.read_text(encoding='utf-8-sig')
    audio = setting(text, 'AudioLanguage')
    ui = setting(text, 'UILanguage')
    return {'audio': audio, 'ui': ui, 'folder': str(game / ('dota_' + audio)) if audio in LANGUAGES else None}


def install(package, game):
    core.ensure_game_closed()
    game = core.game_directory(game)
    package = Path(package).resolve()
    manifest = core.check_package(package)
    previous_folder, previous = installation(game, verify=True)
    boot = game / 'dota/cfg/boot.vcfg'
    if not boot.is_file():
        raise ValueError('Не найден dota/cfg/boot.vcfg. Запустите Dota один раз и закройте её')
    original_boot = boot.read_bytes()
    language = setting(original_boot.decode('utf-8-sig'), 'AudioLanguage')
    if language not in LANGUAGES:
        # Keep English speech: pick an existing language layer with no Valve
        # voice pack. UI-only archives installed by us are not speech packs.
        candidates = [candidate for candidate in LANGUAGES
                      if (game / ('dota_' + candidate) / 'gameinfo.gi').is_file()
                      and not (game / ('dota_' + candidate) / 'pak01_dir.vpk').exists()
                      and not (game / ('dota_' + candidate) / 'sounds').exists()]
        if not candidates:
            raise ValueError('Не найдена штатная языковая папка без озвучки: автоматическая установка изменила бы английскую речь')
        language = candidates[0]
    target = game / ('dota_' + language)
    if target.is_symlink() or not (target / 'gameinfo.gi').is_file():
        raise ValueError(f'Не найдена штатная папка {target.name} с gameinfo.gi')
    # Preflight the real VPK and preserve other mods/Valve's voice archives.
    files = {}
    for name in sorted(manifest['files']):
        archive = VPK(package / name)
        for entry in archive.entries:
            files[entry] = archive.read(entry)
    for archive_path in target.glob('pak??_dir.vpk'):
        if previous_folder == target and archive_path.name in previous['owned_files']:
            continue
        conflicts = set(VPK(archive_path).entries).intersection(files)
        if conflicts:
            raise ValueError(f'Другой архив уже заменяет тот же ресурс: {archive_path.name}: {sorted(conflicts)[0]}')
    available = [f'pak{i:02d}_dir.vpk' for i in range(30, 100) if i not in (64, 65, 66, 67)
                 and not (target / f'pak{i:02d}_dir.vpk').exists()]
    if previous_folder == target:
        name = next(iter(previous['owned_files']))
    elif available:
        name = available[0]
    else:
        raise ValueError('Нет свободного слота VPK в языковой папке')
    stage = Path(tempfile.mkdtemp(prefix='.dota-mounted-', dir=game))
    backup = None
    installed = False
    try:
        write_vpk(stage / name, files)
        archive = VPK(stage / name)
        for entry in archive.entries:
            archive.read(entry)
        record = {'app': core.APP_ID, 'mount_version': 2, 'language': language, 'package': str(package),
                  'previous_audio': previous['previous_audio'] if previous else setting(original_boot.decode('utf-8-sig'), 'AudioLanguage'),
                  'owned_files': {name: digest(stage / name)}, 'manifest': manifest}
        (stage / MARKER).write_text(json.dumps(record, ensure_ascii=False, indent=2))
        if previous:
            backup = core.backup_path(game)
            backup.mkdir()
            for owned in [*previous['owned_files'], MARKER]:
                (previous_folder / owned).rename(backup / owned)
        try:
            (stage / name).rename(target / name)
            installed = True
            (stage / MARKER).rename(target / MARKER)
            # Change only the audio setting. Preserve the user's UI language.
            if boot.read_bytes() != original_boot:
                raise ValueError('Игра изменила boot.vcfg во время установки; закройте Dota и повторите')
            atomic(boot, set_audio(original_boot, language))
            installation(game, verify=True)
        except BaseException:
            if installed:
                (target / name).unlink(missing_ok=True)
                (target / MARKER).unlink(missing_ok=True)
            if backup:
                for saved in backup.iterdir():
                    saved.rename(previous_folder / saved.name)
            if boot.read_bytes() == set_audio(original_boot, language):
                atomic(boot, original_boot)
            raise
    finally:
        shutil.rmtree(stage)
    return target / name, backup


def disable(game):
    core.ensure_game_closed()
    game = core.game_directory(game)
    folder, record = installation(game, verify=True)
    if not record:
        return core.disable(game)
    backup = core.backup_path(game)
    backup.mkdir()
    moved = []
    boot = game / 'dota/cfg/boot.vcfg'
    original_boot = boot.read_bytes()
    try:
        for name in [*record['owned_files'], MARKER]:
            (folder / name).rename(backup / name)
            moved.append(name)
        if setting(original_boot.decode('utf-8-sig'), 'AudioLanguage') == record['language']:
            atomic(boot, set_audio(original_boot, record['previous_audio']))
    except BaseException:
        for name in moved:
            (backup / name).rename(folder / name)
        raise
    return backup
