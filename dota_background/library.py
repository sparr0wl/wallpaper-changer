"""Persistent media library and reversible per-game font switches."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid

from . import core, media
from . import mounts
from .vpk import VPK
from .runtime import data_directory


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.json-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class Library:
    def __init__(self, storage=None, game=None):
        self.storage = Path(storage) if storage else data_directory()
        self.items_path = self.storage / 'library'
        self.items_path.mkdir(parents=True, exist_ok=True)
        self.config_path = self.storage / 'settings.json'
        self.settings = read_json(self.config_path, {})
        games = core.discover_games() if game is None and not self.settings.get('game') else []
        configured = game or self.settings.get('game') or (games[0] if games else None)
        try:
            self.game = core.game_directory(configured) if configured else None
        except ValueError:
            if game is not None:
                raise
            self.game = None
        self.template = Path(self.settings.get('template', self.storage / 'templates/local-base'))

    def item_path(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{24}', identifier):
            raise ValueError('Неверный идентификатор фона')
        return self.items_path / identifier

    def items(self):
        items = []
        for path in sorted(self.items_path.glob('*/item.json')):
            info = read_json(path)
            if info:
                info['preview_url'] = (path.parent / 'preview.jpg').as_uri()
                info['video_url'] = (path.parent / info['source']).as_uri()
                items.append(info)
        return sorted(items, key=lambda item: item.get('created', ''), reverse=True)

    def import_video(self, source, title=None, origin='user'):
        source = Path(source).expanduser().resolve()
        info = media.probe(source)
        if source.stat().st_size > 2 * 1024**3:
            raise ValueError('Выберите видео размером до 2 ГиБ')
        checksum = sha(source)
        identifier = checksum[:24]
        destination = self.item_path(identifier)
        if (destination / 'item.json').is_file():
            return identifier
        stage = Path(tempfile.mkdtemp(prefix='.import-', dir=self.items_path))
        try:
            extension = source.suffix.lower() if re.fullmatch(r'\.[a-z0-9]{1,8}', source.suffix.lower()) else '.video'
            saved = stage / ('source' + extension)
            shutil.copyfile(source, saved)
            media.thumbnail(saved, stage / 'preview.jpg')
            record = {'id': identifier, 'title': title or source.stem, 'source': saved.name,
                      'sha256': checksum, 'media': info, 'origin': origin,
                      'created': datetime.datetime.now(datetime.timezone.utc).isoformat()}
            write_json(stage / 'item.json', record)
            stage.rename(destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return identifier

    def migrate(self):
        """Import current installed/previous packages and the user's eight sample videos once."""
        imported = self.settings.get('imported_packages', {})
        candidates = list((self.storage / 'templates/wftrmaked').glob('*/dota_123'))
        candidates += list((self.storage / 'packages').glob('*'))
        if self.game:
            candidates += [self.game / 'dota_123']
            candidates += list((self.game / '.dota-background-backups').glob('*'))
        for folder in candidates:
            if not folder.is_dir():
                continue
            archives = sorted(folder.glob('*_dir.vpk'))
            key = str(folder)
            stamp = [(p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in archives]
            signature = json.dumps(stamp)
            if not archives or imported.get(key) == signature:
                continue
            for archive_path in archives:
                archive = VPK(archive_path)
                videos = [n for n in archive.entries if n.endswith('.webm')]
                if len(videos) != 1:
                    continue
                data = archive.read(videos[0])
                title = 'Фон ' + folder.parent.name if folder.parent.parent.name == 'wftrmaked' else 'Ранее установленный фон'
                with tempfile.TemporaryDirectory(prefix='.vpk-video-', dir=self.storage) as tmp:
                    video = Path(tmp) / 'background.webm'
                    video.write_bytes(data)
                    self.import_video(video, title, origin='existing')
            imported[key] = signature
        self.settings['imported_packages'] = imported
        write_json(self.config_path, self.settings)

    def dimensions(self, size=None):
        if size:
            return media.valid_size(size)
        if self.settings.get('resolution'):
            return media.valid_size(self.settings['resolution'])
        screens = media.monitors()
        if screens:
            screen = screens[0]
            return media.valid_size((screen['width'], screen['height']))
        return (1920, 1080)

    def activate(self, identifier, size=None, progress=None):
        if self.game is None:
            raise ValueError('Укажите папку Dota 2 в настройках')
        core.ensure_game_closed()
        if not self.template.exists():
            if progress:
                progress(0, 'Первый запуск: загрузка основы видеофона')
            from .templates import download_template
            self.template, _ = download_template(self.storage / 'templates/local-base')
            self.settings['template'] = str(self.template)
            write_json(self.config_path, self.settings)
        item_path = self.item_path(identifier)
        item = read_json(item_path / 'item.json')
        if item is None:
            raise ValueError('Фон не найден в библиотеке')
        source = item_path / item['source']
        dimensions = self.dimensions(size)
        render = item_path / f'video-{dimensions[0]}x{dimensions[1]}.webm'
        if not render.exists():
            if progress:
                progress(0, 'Подгонка под монитор и конвертация в WebM')
            info = media.probe(source)
            if (source.suffix == '.webm' and info['codec'] in ('vp8', 'vp9') and info['size'] < 20_000_000
                    and (info['width'], info['height']) == dimensions):
                shutil.copyfile(source, render)
            else:
                media.convert(source, render, dimensions, lambda percent: progress(percent, 'Конвертация видео') if progress else None)
        core.video_info(render)
        package = item_path / 'packages' / uuid.uuid4().hex
        if progress:
            progress(96, 'Актуальный фикс события и сборка пакета')
        core.build_background(self.template, render, package, scene_game=self.game)
        manifest = read_json(package / core.MARKER)
        manifest['library_id'] = identifier
        write_json(package / core.MARKER, manifest)
        from .steam_options import remove_obsolete
        target, backup = mounts.install(package, self.game)
        remove_obsolete(self.storage)
        if (self.game / 'dota_123' / core.MARKER).is_file():
            legacy_backup = core.disable(self.game)
            backup = backup or legacy_backup
        item['last_package'] = str(package)
        item['render_size'] = list(dimensions)
        write_json(item_path / 'item.json', item)
        self.settings['active'] = identifier
        write_json(self.config_path, self.settings)
        if progress:
            progress(100, 'Фон установлен')
        return {'target': str(target), 'backup': str(backup) if backup else None, 'scene_fix': manifest['scene_fix']}

    def repair_scene(self):
        """Preserve installed video bytes; replace only the obsolete fix package."""
        if self.game is None:
            raise ValueError('Dota 2 не найдена')
        core.ensure_game_closed()
        installed = mounts.installed_package(self.game)
        manifest = core.check_package(installed)
        video_name = manifest['video_path']
        data = None
        for name in manifest['files']:
            archive = VPK(installed / name)
            if video_name in archive.entries:
                data = archive.read(video_name)
                break
        if data is None:
            raise ValueError('Установленное видео не найдено')
        destination = self.storage / 'packages' / ('event-fix-' + uuid.uuid4().hex)
        with tempfile.TemporaryDirectory(prefix='.repair-', dir=self.storage) as tmp:
            video = Path(tmp) / 'video.webm'
            video.write_bytes(data)
            core.build_background(installed, video, destination, video_name, scene_game=self.game)
        updated = read_json(destination / core.MARKER)
        if manifest.get('library_id'):
            updated['library_id'] = manifest['library_id']
            write_json(destination / core.MARKER, updated)
        from .steam_options import remove_obsolete
        target, backup = mounts.install(destination, self.game)
        remove_obsolete(self.storage)
        if (self.game / 'dota_123' / core.MARKER).is_file():
            legacy_backup = core.disable(self.game)
            backup = backup or legacy_backup
        return {'target': str(target), 'backup': str(backup), 'scene_fix': updated['scene_fix']}

    def active(self):
        if not self.game:
            return None, None
        try:
            folder, mounted = mounts.installation(self.game)
            # Only read status here; full checksums are verified before mutations.
            manifest = mounted['manifest'] if mounted else read_json(self.game / 'dota_123' / core.MARKER, {})
            if manifest.get('app') != core.APP_ID:
                return None, None
            identifier = manifest.get('library_id')
            if identifier is None:
                video = manifest.get('video_path')
                for name in manifest.get('files', {}):
                    archive = VPK((Path(mounted['package']) if mounted else self.game / 'dota_123') / name)
                    if video in archive.entries:
                        identifier = hashlib.sha256(archive.read(video)).hexdigest()[:24]
                        break
            return identifier, manifest.get('scene_fix')
        except (OSError, ValueError, KeyError):
            return None, None


class Fonts:
    def __init__(self, game, storage):
        self.game = Path(game)
        game_id = hashlib.sha256(str(self.game.resolve()).encode()).hexdigest()[:16]
        self.root = Path(storage) / 'fonts' / game_id
        self.record = self.root / 'state.json'
        self.state = read_json(self.record, {})

    def catalog(self):
        root = self.game / 'dota/panorama/fonts'
        fonts = {}
        for p in sorted(root.iterdir()) if root.is_dir() else []:
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.otf', '.ttf', '.uifont', '.vfont'):
                fonts[p.name] = {'name': p.name, 'title': p.stem.replace('-', ' ').replace('_', ' ').title(), 'enabled': True}
        for name, record in self.state.items():
            if record.get('disabled'):
                fonts[name] = {'name': name, 'title': Path(name).stem.replace('-', ' ').replace('_', ' ').title(),
                               'enabled': (root / name).is_file()}
        return sorted(fonts.values(), key=lambda font: font['name'])

    def toggle(self, name, enabled):
        core.ensure_game_closed()
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+\.(otf|ttf|uifont|vfont)', name):
            raise ValueError('Недопустимое имя шрифта')
        target = self.game / 'dota/panorama/fonts' / name
        if target.is_symlink():
            raise ValueError('Шрифт не должен быть символической ссылкой')
        record = self.state.get(name)
        if enabled:
            if not record or not record.get('disabled'):
                if target.is_file():
                    return
                raise ValueError('Нет резервной копии шрифта')
            backup = self.root / record['backup']
            if not backup.is_file() or sha(backup) != record['sha256']:
                raise ValueError('Резервная копия шрифта повреждена')
            if target.exists():
                if sha(target) != record['sha256']:
                    raise ValueError('Steam обновил шрифт: оставляем новую версию, требуется ручная проверка копии')
            else:
                # Keep the backup even after re-enabling; never overwrite Steam's files.
                with target.open('xb') as f, backup.open('rb') as source:
                    shutil.copyfileobj(source, f)
                if sha(target) != record['sha256']:
                    raise ValueError('Восстановленный шрифт не прошёл проверку')
            record['disabled'] = False
            write_json(self.record, self.state)
        else:
            if not target.is_file():
                if record and record.get('disabled'):
                    return
                raise ValueError('Шрифт не найден')
            if record and record.get('disabled'):
                raise ValueError('Steam восстановил шрифт. Сначала включите его в приложении и повторите действие')
            self.root.mkdir(parents=True, exist_ok=True)
            backup_name = uuid.uuid4().hex + '-' + name
            backup = self.root / backup_name
            checksum = sha(target)
            shutil.copyfile(target, backup)
            if sha(backup) != checksum:
                raise ValueError('Не удалось проверить резервную копию')
            # Save recovery information before removing the game's copy.
            self.state[name] = {'backup': backup_name, 'sha256': checksum, 'disabled': True}
            write_json(self.record, self.state)
            if sha(target) != checksum:
                raise ValueError('Шрифт изменился во время операции; исходный файл сохранён')
            target.unlink()
