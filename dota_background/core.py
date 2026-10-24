"""Background package construction and reversible installation."""
from __future__ import annotations

from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

from .vpk import VPK, VPKError, safe_name, write_vpk

MARKER = '.dota-background.json'
APP_ID = 'dota-background-changer-v1'
MAX_VIDEO = 30_000_000
MAX_TEMPLATE = 256 * 1024 * 1024
GUIDE = 'https://steamcommunity.com/sharedfiles/filedetails/?id=3360663587'


def game_directory(path):
    p = Path(path).expanduser().resolve()
    for candidate in (p, p / 'game', p.parent if p.name == 'dota' else p):
        if (candidate / 'dota' / 'gameinfo.gi').is_file():
            return candidate
    raise ValueError('Выберите dota 2 beta, game или game/dota: файл dota/gameinfo.gi не найден')


def discover_games():
    home = Path.home()
    roots = [home / '.local/share/Steam', home / '.steam/steam', home / 'Library/Application Support/Steam']
    for env in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]) / 'Steam')
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                roots.append(Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
        except OSError:
            pass
    libraries = set(roots)
    for root in roots:
        config = root / 'steamapps/libraryfolders.vdf'
        if config.is_file():
            for match in re.finditer(r'"path"\s+"([^"]+)"', config.read_text(errors='replace')):
                libraries.add(Path(match[1].replace('\\\\', '\\')))
    result = set()
    for root in libraries:
        try:
            result.add(game_directory(root / 'steamapps/common/dota 2 beta'))
        except ValueError:
            pass
    return sorted(result)


def video_info(path):
    path = Path(path)
    if path.suffix.lower() != '.webm' or not path.is_file():
        raise ValueError('Выберите существующий файл .webm')
    if not 0 < path.stat().st_size <= MAX_VIDEO:
        raise ValueError('Видео должно занимать от 1 байта до 30 МБ (ограничение из гайда)')
    with path.open('rb') as f:
        if f.read(4) != b'\x1a\x45\xdf\xa3':
            raise ValueError('Файл не содержит заголовок WebM/EBML')
    probe = shutil.which('ffprobe')
    if not probe:
        raise ValueError('Для проверки видео нужен ffprobe из пакета FFmpeg')
    result = subprocess.run([probe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('ffprobe не смог прочитать видео: ' + result.stderr[-500:])
    details = json.loads(result.stdout)
    streams = [s for s in details.get('streams', []) if s.get('codec_type') == 'video']
    if not streams or streams[0].get('codec_name') not in ('vp8', 'vp9'):
        raise ValueError('Требуется WebM с видеокодеком VP8 или VP9')
    stream = streams[0]
    return {'codec': stream['codec_name'], 'width': stream['width'], 'height': stream['height'],
            'size': path.stat().st_size, 'duration': details.get('format', {}).get('duration', '?')}


def load_template(path):
    """Accept a prepared background VPK, unpacked asset folder, or dota_123 folder."""
    path = Path(path).expanduser().resolve()
    packages = {}
    total = 0
    if path.is_file():
        archives = [path]
    elif path.is_dir():
        archives = sorted(path.glob('*.vpk'))
        archives = [p for p in archives if not re.search(r'_\d{3}\.vpk$', p.name)]
    else:
        raise ValueError('Шаблон не найден')
    if archives:
        if len(archives) > 8:
            raise ValueError('Слишком много архивов: выберите папку готового фона, а не оригинальные архивы Dota')
        for index, archive in enumerate(archives, 1):
            vpk = VPK(archive)
            total += sum(e.size for e in vpk.entries.values())
            if total > MAX_TEMPLATE:
                raise ValueError('Шаблон больше 256 МиБ. Нужен небольшой VPK готового фона из гайда')
            packages[f'pak{index:02d}_dir.vpk'] = {n: vpk.read(n, MAX_TEMPLATE) for n in vpk.entries}
    else:
        files = {}
        for item in sorted(path.rglob('*')):
            if item.is_symlink():
                raise ValueError('Символические ссылки в шаблоне не поддерживаются')
            if item.is_file() and item.name != MARKER:
                name = item.relative_to(path).as_posix()
                safe_name(name)
                total += item.stat().st_size
                if total > MAX_TEMPLATE:
                    raise ValueError('Шаблон больше 256 МиБ')
                files[name] = item.read_bytes()
        packages['pak01_dir.vpk'] = files
    names = [n for files in packages.values() for n in files]
    if not any(n.startswith('panorama/') and '/layout/' in n for n in names):
        raise ValueError('В шаблоне нет panorama/layout. Выберите корень папки с 123 и panorama или VPK готового фона')
    return packages


def video_targets(packages):
    return sorted({n for files in packages.values() for n in files if n.lower().endswith('.webm')})


def build_background(template, video, output, target=None, scene_game=None):
    info = video_info(video)
    packages = load_template(template)
    scene_report = None
    if scene_game:
        from .scene import current_fix, CUSTOM_BACKGROUND
        if not any(CUSTOM_BACKGROUND + '_c' in files for files in packages.values()):
            raise ValueError('Основа не содержит видеосцену dashboard_background_last_match')
        fix, scene_report = current_fix(game_directory(scene_game))
        for files in packages.values():
            files.pop('panorama/layout/dashboard.vxml_c', None)
            files.pop('panorama/styles/battle_pass/crownfall/bp_background_crownfall.vcss_c', None)
        # Discard the outdated Crownfall fix. Current dashboard keeps current controls.
        packages['pak02_dir.vpk'] = fix
    targets = video_targets(packages)
    if target:
        safe_name(target)
        if not target.lower().endswith('.webm'):
            raise ValueError('Путь видео в VPK должен оканчиваться на .webm')
    elif len(targets) == 1:
        target = targets[0]
    elif len(targets) > 1:
        raise ValueError('В шаблоне несколько WebM: выберите путь заменяемого видео')
    else:
        # The unpacked base linked in the guide references this exact path.
        target = '123/123.webm'
    matching = [files for files in packages.values() if target in files]
    if targets and not matching:
        raise ValueError('Выбранный путь отсутствует в шаблоне; доступно: ' + ', '.join(targets))
    if not matching:
        matching = [next(iter(packages.values()))]
    video_data = Path(video).read_bytes()
    for files in matching:
        files[target] = video_data
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError('Папка результата уже существует. Выберите новое имя')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.dota-build-', dir=output.parent))
    try:
        checksums = {}
        for name, files in packages.items():
            write_vpk(stage / name, files)
            packed = VPK(stage / name)
            for entry in packed.entries:
                packed.read(entry, MAX_TEMPLATE)
            checksums[name] = hashlib.sha256((stage / name).read_bytes()).hexdigest()
        manifest = {'app': APP_ID, 'created': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'video_path': target, 'video': info, 'files': checksums, 'guide': GUIDE}
        if scene_report:
            manifest['scene_fix'] = scene_report
        (stage / MARKER).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest


def check_package(path):
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Ожидается обычная папка пакета')
    marker = path / MARKER
    if marker.is_symlink():
        raise ValueError('Недопустимая ссылка на манифест')
    try:
        data = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ValueError('Папка не создана этой программой; автоматическая замена запрещена') from e
    if data.get('app') != APP_ID or not isinstance(data.get('files'), dict) or not data['files']:
        raise ValueError('Неверный манифест пакета')
    expected = {MARKER}
    for name, checksum in data['files'].items():
        if not re.fullmatch(r'pak\d{2}_dir\.vpk', name):
            raise ValueError('Недопустимое имя архива в манифесте')
        file = path / name
        if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
            raise ValueError(f'Пакет изменён или повреждён: {name}. Сохраните изменения вручную')
        expected.add(name)
    if {p.name for p in path.iterdir()} != expected:
        raise ValueError('В папке есть посторонние файлы; сохраните их вручную перед заменой')
    return data


def ensure_game_closed():
    if os.name == 'posix' and Path('/proc').exists():
        for p in Path('/proc').glob('[0-9]*/comm'):
            try:
                if p.read_text().strip().lower() in ('dota2', 'dota2.exe', 'dota2_linux'):
                    raise ValueError('Закройте Dota 2 перед изменением фона')
            except OSError:
                continue
    elif os.name == 'nt':
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq dota2.exe', '/FO', 'CSV'],
                                capture_output=True, text=True, timeout=15)
        if 'dota2.exe' in result.stdout.lower():
            raise ValueError('Закройте Dota 2 перед изменением фона')


def backup_path(game):
    root = game / '.dota-background-backups'
    if root.is_symlink():
        raise ValueError('Каталог резервных копий не должен быть ссылкой')
    root.mkdir(exist_ok=True)
    return root / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')


def install(package, game):
    ensure_game_closed()
    game = game_directory(game)
    package = Path(package).resolve()
    check_package(package)
    target = game / 'dota_123'
    if package == target.resolve():
        raise ValueError('Этот пакет уже установлен')
    if target.exists() or target.is_symlink():
        check_package(target)
    stage = Path(tempfile.mkdtemp(prefix='.dota-install-', dir=game))
    backup = None
    try:
        shutil.copytree(package, stage, dirs_exist_ok=True)
        check_package(stage)
        if target.exists():
            backup = backup_path(game)
            target.rename(backup)
        try:
            stage.rename(target)
        except BaseException:
            if backup:
                backup.rename(target)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target, backup


def disable(game):
    ensure_game_closed()
    game = game_directory(game)
    target = game / 'dota_123'
    check_package(target)
    backup = backup_path(game)
    target.rename(backup)
    return backup
