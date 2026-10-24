from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from dota_background import core
from dota_background.templates import extract_zip, import_zip
from dota_background.vpk import VPK, write_vpk


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = self.root / 'template'
        self.template.mkdir()
        self.assets = {'panorama/layout/dashboard.vxml_c': b'test fixture, not a real UI resource',
                       '123/123.webm': b'old video'}
        write_vpk(self.template / 'pak01_dir.vpk', self.assets)
        write_vpk(self.template / 'pak02_dir.vpk', {'panorama/layout/event.vxml_c': b'event fix fixture'})
        self.video = self.root / 'custom.webm'
        self.video.write_bytes(b'new video')
        self.game = self.root / 'dota 2 beta/game'
        (self.game / 'dota').mkdir(parents=True)
        (self.game / 'dota/gameinfo.gi').write_text('original')
        self.original = self.game / 'dota/pak01_dir.vpk'
        self.original.write_bytes(b'original game data')
        self.probe = patch.object(core, 'video_info', return_value={'codec': 'vp9', 'width': 32, 'height': 32})
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.closed = patch.object(core, 'ensure_game_closed')
        self.closed.start()
        self.addCleanup(self.closed.stop)

    def build(self, name='result'):
        output = self.root / name
        core.build_background(self.template, self.video, output)
        return output

    def test_build_preserves_layout_and_event_fix(self):
        package = self.build()
        archive = VPK(package / 'pak01_dir.vpk')
        self.assertEqual(archive.read('123/123.webm'), b'new video')
        self.assertEqual(archive.read('panorama/layout/dashboard.vxml_c'), self.assets['panorama/layout/dashboard.vxml_c'])
        self.assertEqual(VPK(package / 'pak02_dir.vpk').read('panorama/layout/event.vxml_c'), b'event fix fixture')
        self.assertEqual(VPK(self.template / 'pak01_dir.vpk').read('123/123.webm'), b'old video')
        core.check_package(package)
        with self.assertRaises(ValueError):
            self.build()

    def test_install_replace_disable_restore_and_preserve_original(self):
        package = self.build()
        target, backup = core.install(package, self.game.parent)
        self.assertIsNone(backup)
        self.assertEqual(target, self.game / 'dota_123')
        self.video.write_bytes(b'next video')
        second = self.build('second')
        _, backup = core.install(second, self.game)
        core.check_package(backup)
        self.assertEqual(VPK(backup / 'pak01_dir.vpk').read('123/123.webm'), b'new video')
        disabled = core.disable(self.game)
        self.assertFalse(target.exists())
        core.check_package(disabled)
        core.install(backup, self.game)
        self.assertEqual(VPK(target / 'pak01_dir.vpk').read('123/123.webm'), b'new video')
        self.assertEqual(self.original.read_bytes(), b'original game data')
        self.assertEqual((self.game / 'dota/gameinfo.gi').read_text(), 'original')

    def test_foreign_and_modified_folders_refused(self):
        package = self.build()
        target = self.game / 'dota_123'
        target.mkdir()
        (target / 'personal.txt').write_text('keep')
        with self.assertRaises(ValueError):
            core.install(package, self.game)
        self.assertEqual((target / 'personal.txt').read_text(), 'keep')
        shutil.rmtree(target)
        core.install(package, self.game)
        (target / 'extra.txt').write_text('keep')
        with self.assertRaises(ValueError):
            core.disable(self.game)
        (target / 'extra.txt').unlink()
        (target / 'pak01_dir.vpk').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            core.disable(self.game)

    def test_failed_replacement_restores_previous(self):
        package = self.build()
        target, _ = core.install(package, self.game)
        original_rename = Path.rename

        def fail_stage(path, destination):
            if path.name.startswith('.dota-install-'):
                raise OSError('simulated installation failure')
            return original_rename(path, destination)
        with patch.object(Path, 'rename', fail_stage):
            with self.assertRaises(OSError):
                core.install(package, self.game)
        core.check_package(target)

    def test_multiple_video_targets_require_choice(self):
        self.assets['123/second.webm'] = b'other'
        write_vpk(self.template / 'pak01_dir.vpk', self.assets)
        with self.assertRaisesRegex(ValueError, 'несколько'):
            self.build()
        output = self.root / 'chosen'
        core.build_background(self.template, self.video, output, '123/second.webm')
        archive = VPK(output / 'pak01_dir.vpk')
        self.assertEqual(archive.read('123/second.webm'), b'new video')
        self.assertEqual(archive.read('123/123.webm'), b'old video')

    def test_bad_template_rejected(self):
        write_vpk(self.root / 'bad.vpk', {'other.txt': b'hello'})
        with self.assertRaisesRegex(ValueError, 'panorama/layout'):
            core.load_template(self.root / 'bad.vpk')

    def test_zip_import_and_traversal(self):
        archive = self.root / 'template.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            for file in self.template.iterdir():
                z.write(file, 'nested/dota_123/' + file.name)
        destination = import_zip(archive, self.root / 'imported')
        self.assertEqual(len(core.load_template(destination)), 2)
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../escape.txt', b'no')
        with self.assertRaises(ValueError):
            extract_zip(archive, self.root / 'unpacked')
        self.assertFalse((self.root / 'escape.txt').exists())


class RealVideoTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg not installed')
    def test_real_vp9_video_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / 'sample.webm'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:d=0.2',
                            '-c:v', 'libvpx-vp9', '-an', str(video)], check=True, timeout=30)
            info = core.video_info(video)
            self.assertEqual((info['codec'], info['width'], info['height']), ('vp9', 64, 64))
            video.write_bytes(b'not a video')
            with self.assertRaises(ValueError):
                core.video_info(video)


if __name__ == '__main__':
    unittest.main()
