"""Precisely remove our obsolete -language 123 option without logging Steam data."""
from pathlib import Path
import hashlib
import json
import re

from .mounts import atomic


def launch_option_span(text):
    # Walk KeyValues scopes, so auth tickets with a key '570' are never selected.
    token = re.compile(r'//[^\r\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+')
    tokens = [m for m in token.finditer(text) if not m[0].startswith('//')]
    position = 0
    found = []

    def decode(raw):
        if raw.startswith('"'):
            return re.sub(r'\\(["\\])', r'\1', raw[1:-1])
        return raw

    def scope(path):
        nonlocal position
        while position < len(tokens):
            key = tokens[position]
            position += 1
            if key[0] == '}':
                return
            if key[0] == '{' or position == len(tokens):
                raise ValueError('Некорректная структура localconfig.vdf')
            name = decode(key[0]).lower()
            value = tokens[position]
            position += 1
            if value[0] == '{':
                scope(path + [name])
            elif value[0] == '}':
                raise ValueError('Некорректное значение localconfig.vdf')
            elif name == 'launchoptions' and path[-2:] == ['apps', '570']:
                found.append((value.start(), value.end(), decode(value[0])))
    scope([])
    if len(found) > 1:
        raise ValueError('Несколько LaunchOptions для Dota: файл не изменён')
    return found[0] if found else None


def configs():
    roots = [Path.home() / '.local/share/Steam/userdata', Path.home() / '.steam/steam/userdata']
    return sorted({p.resolve() for root in roots for p in root.glob('*/config/localconfig.vdf')})


def obsolete_options():
    found = []
    for path in configs():
        span = launch_option_span(path.read_text(encoding='utf-8'))
        if span and re.search(r'(?<!\S)-language\s+(?:"123"|123)(?=\s|$)', span[2], re.I):
            found.append(str(path))
    return found


def remove_obsolete(storage):
    changes = []
    for path in configs():
        raw = path.read_bytes()
        text = raw.decode('utf-8')
        span = launch_option_span(text)
        if not span:
            continue
        start, end, previous = span
        value = re.sub(r'(?<!\S)-language\s+(?:"123"|123)(?=\s|$)', '', previous, flags=re.I).strip()
        if value == previous:
            continue
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        updated = (text[:start] + '"' + escaped + '"' + text[end:]).encode('utf-8')
        backup_root = Path(storage) / 'steam-launch-backups'
        backup_root.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256((str(path) + previous).encode()).hexdigest()[:24]
        # Back up only this setting: never copy auth tickets into app diagnostics.
        backup = backup_root / (key + '.json')
        if not backup.exists():
            backup.write_text(json.dumps({'path': str(path), 'previous': previous, 'updated': value}, ensure_ascii=False, indent=2))
        if path.read_bytes() != raw:
            raise ValueError('Steam изменил настройки во время операции; повторите после закрытия Steam')
        atomic(path, updated)
        checked = launch_option_span(path.read_text(encoding='utf-8'))
        if not checked or checked[2] != value:
            atomic(path, raw)
            raise ValueError('Проверка параметров Steam не прошла; исходное значение восстановлено')
        changes.append(str(path))
    return changes
