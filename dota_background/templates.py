"""Download/import data-only templates; never execute downloaded content."""
from pathlib import Path
import json
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile

from .core import MAX_TEMPLATE, load_template
from .vpk import safe_name

BASE_URL = 'https://drive.google.com/uc?export=download&id=1KxC6W2qzwduwOT5Yfoa1td8TzElqnabl'
FIX_URL = 'https://drive.google.com/uc?export=download&id=1Y1j_ZLNt3hG3MKmbfhh5I3PsmOoeCISV'
MIRROR_GUIDE = 'https://steamcommunity.com/sharedfiles/filedetails/?id=3500310450'
YANDEX_BASE = 'https://disk.yandex.ru/d/TMN-vUHCO6kMbw'


def extract_zip(archive, destination):
    root = Path(destination).resolve()
    total = 0
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 10000:
            raise ValueError('В ZIP слишком много файлов')
        for entry in entries:
            safe_name(entry.filename.rstrip('/'))
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Ссылки в ZIP не поддерживаются')
            total += entry.file_size
            if total > MAX_TEMPLATE:
                raise ValueError('Распакованный шаблон больше 256 МиБ')
        root.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            target = root / entry.filename
            if not target.resolve().is_relative_to(root):
                raise ValueError('Путь ZIP выходит за каталог')
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)


def download(url, destination, limit=MAX_TEMPLATE):
    request = urllib.request.Request(url, headers={'User-Agent': 'DotaBackgroundChanger/1.0'})
    total = 0
    with urllib.request.urlopen(request, timeout=30) as response, Path(destination).open('xb') as f:
        if 'text/html' in response.headers.get('Content-Type', ''):
            raise ValueError('Сервер вернул страницу вместо ZIP. Скачайте основу вручную по ссылке в README')
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError('Загрузка превышает 256 МиБ')
            f.write(chunk)


def find_asset_root(root):
    candidates = [Path(root)] + sorted(p.parent for p in Path(root).rglob('panorama') if p.is_dir())
    for candidate in candidates:
        if (candidate / 'panorama/layout').is_dir():
            return candidate
    raise ValueError('В основе не найдена папка panorama/layout')


def import_zip(archive, destination):
    """Normalize a full background ZIP into a folder containing portable VPKs."""
    from .vpk import write_vpk
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Выберите новую папку для импорта')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.dota-template-', dir=destination.parent) as tmp:
        raw = Path(tmp) / 'raw'
        extract_zip(archive, raw)
        import re
        archive_roots = sorted({p.parent for p in raw.rglob('*.vpk') if not re.search(r'_\d{3}\.vpk$', p.name)})
        if len(archive_roots) > 1:
            raise ValueError('В ZIP несколько фонов: распакуйте его вручную и выберите один')
        candidate = archive_roots[0] if archive_roots else find_asset_root(raw)
        packages = load_template(candidate)
        staged = Path(tmp) / 'result'
        staged.mkdir()
        for name, files in packages.items():
            write_vpk(staged / name, files)
        staged.rename(destination)
    return destination


def download_template(destination):
    """Fetch base+event fix from the second guide, falling back to original base."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Папка шаблона уже существует; выберите новое имя')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.dota-download-', dir=destination.parent) as tmp:
        tmp = Path(tmp)
        warning = ''
        try:
            download(BASE_URL, tmp / 'base.zip')
        except (OSError, ValueError) as mirror_error:
            api = 'https://cloud-api.yandex.net/v1/disk/public/resources/download?' + urllib.parse.urlencode({'public_key': YANDEX_BASE})
            try:
                with urllib.request.urlopen(api, timeout=30) as response:
                    href = json.load(response)['href']
                if urllib.parse.urlparse(href).scheme != 'https':
                    raise ValueError('Ссылка загрузки должна использовать HTTPS')
                (tmp / 'base.zip').unlink(missing_ok=True)
                download(href, tmp / 'base.zip')
            except (OSError, ValueError, KeyError) as original_error:
                raise ValueError(f'Не удалось скачать основу. Google Drive: {mirror_error}; Яндекс: {original_error}. '
                                 'Можно скачать ZIP вручную и нажать «Импорт ZIP»') from original_error
        extract_zip(tmp / 'base.zip', tmp / 'base')
        root = find_asset_root(tmp / 'base')
        packages = load_template(root)
        try:
            download(FIX_URL, tmp / 'fix.zip')
            extract_zip(tmp / 'fix.zip', tmp / 'fix')
            fixes = list((tmp / 'fix').rglob('pak02_dir.vpk'))
            if len(fixes) != 1:
                raise ValueError('В архиве не найден единственный pak02_dir.vpk')
            from .vpk import VPK
            fix = VPK(fixes[0])
            if sum(e.size for e in fix.entries.values()) > MAX_TEMPLATE:
                raise ValueError('Слишком большой фикс')
            packages['pak02_dir.vpk'] = {name: fix.read(name) for name in fix.entries}
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            warning = f'Основа загружена без pak02 (фикс меню недоступен): {e}. Совместимость с текущим событием не подтверждена.'
        from .vpk import write_vpk
        staged = tmp / 'result'
        staged.mkdir()
        for name, files in packages.items():
            write_vpk(staged / name, files)
        staged.rename(destination)
    return destination, warning
