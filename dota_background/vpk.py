"""Valve VPK v1/v2 reader and deterministic single-file v2 writer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import io
import os
import struct
import tempfile
import zlib


class VPKError(ValueError):
    pass


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or '\0' in name
            or path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/'))):
        raise VPKError(f'Небезопасный путь в VPK: {name!r}')
    return name


@dataclass(frozen=True)
class Entry:
    name: str
    crc: int
    preload: bytes
    archive: int
    offset: int
    length: int

    @property
    def size(self):
        return len(self.preload) + self.length


class VPK:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = {}
        with self.path.open('rb') as f:
            header = f.read(12)
            if len(header) != 12:
                raise VPKError('Обрезанный заголовок VPK')
            magic, self.version, tree_size = struct.unpack('<III', header)
            if magic != 0x55AA1234 or self.version not in (1, 2):
                raise VPKError('Поддерживаются только Valve VPK версий 1 и 2')
            self.header_size = 12 if self.version == 1 else 28
            self.data_size = None
            if self.version == 2:
                extra = f.read(16)
                if len(extra) != 16:
                    raise VPKError('Обрезанный заголовок VPK v2')
                self.data_size, hashes, other, signature = struct.unpack('<IIII', extra)
                if self.header_size + tree_size + self.data_size + hashes + other + signature > self.path.stat().st_size:
                    raise VPKError('Секции VPK выходят за границы файла')
            if tree_size > 64 * 1024 * 1024 or self.header_size + tree_size > self.path.stat().st_size:
                raise VPKError('Некорректный размер дерева VPK')
            raw = f.read(tree_size)
        self.data_start = self.header_size + tree_size
        tree = io.BytesIO(raw)

        def string():
            start = tree.tell()
            end = raw.find(b'\0', start)
            if end < 0:
                raise VPKError('Незавершённая строка в дереве VPK')
            tree.seek(end + 1)
            try:
                return raw[start:end].decode('utf-8')
            except UnicodeDecodeError as e:
                raise VPKError('Путь VPK не является UTF-8') from e

        while ext := string():
            while directory := string():
                while stem := string():
                    meta = tree.read(18)
                    if len(meta) != 18:
                        raise VPKError('Обрезанная запись VPK')
                    crc, preload_size, archive, offset, length, terminator = struct.unpack('<IHHIIH', meta)
                    if terminator != 0xFFFF:
                        raise VPKError('Некорректный терминатор записи VPK')
                    preload = tree.read(preload_size)
                    if len(preload) != preload_size:
                        raise VPKError('Обрезанные preload-данные')
                    name = ('' if directory == ' ' else directory + '/') + stem + ('' if ext == ' ' else '.' + ext)
                    safe_name(name)
                    if name in self.entries:
                        raise VPKError(f'Повторяющийся путь: {name}')
                    self.entries[name] = Entry(name, crc, preload, archive, offset, length)
        if tree.tell() != len(raw):
            raise VPKError('Лишние данные после дерева VPK')

    def read(self, name, limit=512 * 1024 * 1024):
        entry = self.entries[name]
        if entry.size > limit:
            raise VPKError(f'Файл превышает лимит {limit // 1024**2} МиБ: {name}')
        source = self.path
        offset = entry.offset
        if entry.archive == 0x7FFF:
            available = self.data_size if self.data_size is not None else source.stat().st_size - self.data_start
            if offset + entry.length > available:
                raise VPKError(f'Данные выходят за границы VPK: {name}')
            offset += self.data_start
        else:
            if not source.name.endswith('_dir.vpk'):
                raise VPKError('Для многотомного VPK откройте файл *_dir.vpk')
            source = source.with_name(source.name[:-8] + f'_{entry.archive:03d}.vpk')
        if entry.length:
            with source.open('rb') as f:
                if offset + entry.length > source.stat().st_size:
                    raise VPKError(f'Обрезанный архив: {source.name}')
                f.seek(offset)
                data = entry.preload + f.read(entry.length)
        else:
            data = entry.preload
        if zlib.crc32(data) & 0xFFFFFFFF != entry.crc:
            raise VPKError(f'CRC32 не совпадает: {name}')
        return data

    def extract(self, destination, names=None):
        root = Path(destination).resolve()
        root.mkdir(parents=True, exist_ok=True)
        for name in self.entries if names is None else names:
            target = root.joinpath(*PurePosixPath(safe_name(name)).parts)
            if not target.resolve().is_relative_to(root):
                raise VPKError(f'Путь выходит за каталог: {name}')
            data = self.read(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Never overwrite existing files, including symlinks.
            with target.open('xb') as f:
                f.write(data)


def write_vpk(path, files: dict[str, bytes]):
    """Write embedded data with tree/archive/whole-file MD5 sections."""
    groups = {}
    for name, data in sorted(files.items()):
        safe_name(name)
        p = PurePosixPath(name)
        ext = p.suffix[1:] if p.suffix else ' '
        stem = p.name[:-(len(ext) + 1)] if p.suffix else p.name
        directory = str(p.parent) if str(p.parent) != '.' else ' '
        groups.setdefault(ext, {}).setdefault(directory, []).append((stem, data))
    tree = bytearray()
    payload = bytearray()
    for ext, directories in sorted(groups.items()):
        tree.extend(ext.encode() + b'\0')
        for directory, entries in sorted(directories.items()):
            tree.extend(directory.encode() + b'\0')
            for stem, data in entries:
                tree.extend(stem.encode() + b'\0')
                tree.extend(struct.pack('<IHHIIH', zlib.crc32(data) & 0xFFFFFFFF, 0, 0x7FFF, len(payload), len(data), 0xFFFF))
                payload.extend(data)
            tree.extend(b'\0')
        tree.extend(b'\0')
    tree.extend(b'\0')
    header = struct.pack('<7I', 0x55AA1234, 2, len(tree), len(payload), 0, 48, 0)
    hashes = hashlib.md5(tree).digest() + hashlib.md5(b'').digest()
    digest = hashlib.md5(header + tree + payload + hashes).digest()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.vpk-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            for section in (header, tree, payload, hashes, digest):
                f.write(section)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
