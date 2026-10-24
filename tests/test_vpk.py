from pathlib import Path
import hashlib
import struct
import tempfile
import unittest
import zlib

from dota_background.vpk import VPK, VPKError, write_vpk


class VPKTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_round_trip_and_v2_hashes(self):
        files = {'123/123.webm': bytes(range(256)), 'panorama/layout/menu.vxml_c': b'compiled',
                 'empty.txt': b'', 'noextension': b'hello', 'тест/имя.txt': 'Привет'.encode()}
        path = self.root / 'pak01_dir.vpk'
        write_vpk(path, files)
        archive = VPK(path)
        self.assertEqual({name: archive.read(name) for name in archive.entries}, files)
        raw = path.read_bytes()
        tree_size = struct.unpack_from('<I', raw, 8)[0]
        self.assertEqual(raw[-48:-32], hashlib.md5(raw[28:28 + tree_size]).digest())
        self.assertEqual(raw[-16:], hashlib.md5(raw[:-16]).digest())
        archive.extract(self.root / 'out')
        self.assertEqual((self.root / 'out/noextension').read_bytes(), b'hello')
        with self.assertRaises(FileExistsError):
            archive.extract(self.root / 'out')

    def fixture_v1(self, archive_index, preload, payload):
        crc = zlib.crc32(preload + payload)
        tree = b'txt\0folder\0test\0' + struct.pack('<IHHIIH', crc, len(preload), archive_index, 0, len(payload), 0xFFFF)
        tree += preload + b'\0\0\0'
        path = self.root / 'pak01_dir.vpk'
        path.write_bytes(struct.pack('<III', 0x55AA1234, 1, len(tree)) + tree + (payload if archive_index == 0x7FFF else b''))
        if archive_index != 0x7FFF:
            (self.root / f'pak01_{archive_index:03d}.vpk').write_bytes(payload)
        return path

    def test_v1_preload_embedded(self):
        path = self.fixture_v1(0x7FFF, b'pre', b'body')
        self.assertEqual(VPK(path).read('folder/test.txt'), b'prebody')

    def test_v1_external_volume_and_missing_volume(self):
        path = self.fixture_v1(3, b'pre', b'body')
        self.assertEqual(VPK(path).read('folder/test.txt'), b'prebody')
        (self.root / 'pak01_003.vpk').unlink()
        with self.assertRaises(FileNotFoundError):
            VPK(path).read('folder/test.txt')

    def test_corrupt_crc_and_truncated_data_rejected(self):
        path = self.fixture_v1(0x7FFF, b'', b'body')
        data = path.read_bytes()
        path.write_bytes(data[:-1] + b'!')
        with self.assertRaisesRegex(VPKError, 'CRC32'):
            VPK(path).read('folder/test.txt')
        path.write_bytes(data[:-2])
        with self.assertRaises(VPKError):
            VPK(path).read('folder/test.txt')

    def test_bad_headers_and_paths_rejected(self):
        path = self.root / 'bad.vpk'
        for raw in (b'', b'bad' * 10, struct.pack('<III', 0x55AA1234, 9, 0),
                    struct.pack('<III', 0x55AA1234, 1, 1) + b'x'):
            path.write_bytes(raw)
            with self.assertRaises(VPKError):
                VPK(path)
        for name in ('../escape.txt', '/abs.txt', 'C:/file.txt', 'a\\b.txt', 'a/../b.txt', 'a//b.txt'):
            with self.assertRaises(VPKError):
                write_vpk(path, {name: b'data'})

    def test_symlink_escape_rejected(self):
        path = self.root / 'pak.vpk'
        write_vpk(path, {'linked/escape.txt': b'hello'})
        outside = self.root / 'outside'
        outside.mkdir()
        destination = self.root / 'out'
        destination.mkdir()
        try:
            (destination / 'linked').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink privilege unavailable')
        with self.assertRaises(VPKError):
            VPK(path).extract(destination)
        self.assertFalse((outside / 'escape.txt').exists())


if __name__ == '__main__':
    unittest.main()
