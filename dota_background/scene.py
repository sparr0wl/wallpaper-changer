"""Patch the current dashboard's compiled background reference, not an old UI."""
from pathlib import Path
import ctypes
import ctypes.util
import hashlib
import re
import struct

from .vpk import VPK

DASHBOARD = 'panorama/layout/dashboard.vxml_c'
CUSTOM_BACKGROUND = 'panorama/layout/dashboard_background_last_match.vxml'


def lz4(data, size=None):
    library = ctypes.util.find_library('lz4')
    if not library:
        raise ValueError('Нужна системная библиотека liblz4 для актуального фикса меню')
    lib = ctypes.CDLL(library)
    if size is not None:
        if not 0 < size <= 32 * 1024**2:
            raise ValueError('Некорректный размер буфера Panorama')
        function = lib.LZ4_decompress_safe
        function.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        output = ctypes.create_string_buffer(size)
        result = function(data, output, len(data), size)
        if result != size:
            raise ValueError('Повреждён сжатый буфер Panorama')
    else:
        lib.LZ4_compressBound.argtypes = [ctypes.c_int]
        size = lib.LZ4_compressBound(len(data))
        output = ctypes.create_string_buffer(size)
        function = lib.LZ4_compress_default
        function.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        result = function(data, output, len(data), size)
        if result <= 0:
            raise ValueError('Не удалось сжать Panorama')
    return output.raw[:result]


def resource_blocks(raw):
    if len(raw) < 16:
        raise ValueError('Обрезанный ресурс Source 2')
    file_size, header_version, _, offset, count = struct.unpack_from('<IHHII', raw)
    if file_size != len(raw) or header_version != 12 or count > 64:
        raise ValueError('Неизвестный формат ресурса Source 2')
    table = 8 + offset
    blocks = []
    for i in range(count):
        at = table + 12 * i
        tag, relative, size = struct.unpack_from('<4sII', raw, at)
        start = at + 4 + relative
        if start < table + count * 12 or start + size > len(raw):
            raise ValueError('Некорректные границы блока Source 2')
        blocks.append((tag, raw[start:start + size]))
    return blocks


def kv3_strings_buffer(data):
    # Current compiled layouts store the UTF-8 string table in KV3 v5 buffer 1.
    if len(data) < 120 or struct.unpack_from('<I', data)[0] != 0x4B563305:
        raise ValueError('Неподдерживаемая версия LaCo: нужен KV3 v5. Игра могла изменить формат')
    compression = struct.unpack_from('<I', data, 20)[0]
    unpacked_size, packed_size = struct.unpack_from('<II', data, 72)
    if compression == 1:
        buffer = lz4(data[120:120 + packed_size], unpacked_size)
        consumed = packed_size
    elif compression == 0:
        buffer = data[120:120 + unpacked_size]
        consumed = unpacked_size
    else:
        raise ValueError('Неподдерживаемый метод сжатия LaCo')
    return buffer, consumed, compression


def background_references(raw):
    block = next((d for tag, d in resource_blocks(raw) if tag == b'LaCo'), None)
    if block is None:
        raise ValueError('В ресурсе нет скомпилированной разметки LaCo')
    buffer, _, _ = kv3_strings_buffer(block)
    # Match full nul-terminated strings only, preserving all numeric string IDs.
    return sorted({s.decode() for s in buffer.split(b'\0')
                   if re.fullmatch(rb'panorama/layout/[a-zA-Z0-9_/-]*background[a-zA-Z0-9_/-]*\.vxml', s)})


def patch_dashboard(raw, old_reference, new_reference=CUSTOM_BACKGROUND):
    blocks = resource_blocks(raw)
    patched = []
    changes = 0
    for tag, data in blocks:
        if tag == b'LaCo':
            buffer, consumed, compression = kv3_strings_buffer(data)
            old, new = old_reference.encode() + b'\0', new_reference.encode() + b'\0'
            if buffer.count(old) != 1:
                raise ValueError('Ссылка на фон не уникальна; автоматический фикс остановлен')
            updated = buffer.replace(old, new)
            header = bytearray(data[:120])
            delta = len(updated) - len(buffer)
            # Header totals and buffer-1 byte count; buffer 2 and string IDs stay intact.
            for offset in (28, 48, 72):
                struct.pack_into('<I', header, offset, struct.unpack_from('<I', header, offset)[0] + delta)
            packed = lz4(updated) if compression else updated
            if compression:
                difference = len(packed) - consumed
                for offset in (52, 76):
                    struct.pack_into('<I', header, offset, struct.unpack_from('<I', header, offset)[0] + difference)
            data = bytes(header) + packed + data[120 + consumed:]
            changes += 1
        patched.append((tag, data))
    if changes != 1:
        raise ValueError('Ожидался один блок LaCo')
    result = bytearray(raw[:16])
    struct.pack_into('<II', result, 8, 8, len(patched))
    result.extend(b'\0' * (12 * len(patched)))
    for i, (tag, data) in enumerate(patched):
        result.extend(b'\0' * (-len(result) % 4))
        start = len(result)
        at = 16 + 12 * i
        struct.pack_into('<4sII', result, at, tag, start - at - 4, len(data))
        result.extend(data)
    struct.pack_into('<I', result, 0, len(result))
    return bytes(result)


def current_fix(game):
    archive_path = Path(game) / 'dota/pak01_dir.vpk'
    archive = VPK(archive_path)
    raw = archive.read(DASHBOARD)
    references = background_references(raw)
    if len(references) != 1:
        raise ValueError(f'Не удалось однозначно определить фон текущего события: {references}')
    reference = references[0]
    if reference + '_c' not in archive.entries:
        raise ValueError('Файл сцены события отсутствует в архиве игры')
    event_name = None
    scene_blocks = resource_blocks(archive.read(reference + '_c'))
    layout = next((data for tag, data in scene_blocks if tag == b'LaCo'), None)
    if layout is not None:
        strings, _, _ = kv3_strings_buffer(layout)
        title_tokens = re.findall(rb'#(DOTA_[A-Za-z0-9_]+_TreasureTitle)\x00', strings)
        localization_path = 'resource/localization/dota_english.txt'
        if len(title_tokens) == 1 and localization_path in archive.entries:
            localized = archive.read(localization_path)
            encoding = 'utf-16' if localized[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
            text = localized.decode(encoding)
            match = re.search(r'"' + re.escape(title_tokens[0].decode()) + r'"\s*"([^"\r\n]+)"', text)
            if match:
                event_name = match[1]
    patched = patch_dashboard(raw, reference)
    if background_references(patched) != [CUSTOM_BACKGROUND]:
        raise ValueError('Проверка ссылки на пользовательский фон не прошла')
    return {DASHBOARD: patched}, {'source': DASHBOARD, 'event_scene': reference + '_c', 'event_name': event_name,
            'replacement': CUSTOM_BACKGROUND + '_c', 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'archive_size': archive_path.stat().st_size, 'archive_mtime_ns': archive_path.stat().st_mtime_ns,
            'validation': 'compiled-reference-verified; requires in-game confirmation'}
