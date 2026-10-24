from pathlib import Path
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dota_background import core, media
from dota_background import mounts
from dota_background.library import Fonts, Library, read_json, write_json
from dota_background.scene import (CUSTOM_BACKGROUND, DASHBOARD, background_references,
                                   current_fix, kv3_strings_buffer, lz4, patch_dashboard, resource_blocks)
from dota_background.vpk import VPK, write_vpk


EVENT = 'panorama/layout/dashboard_background_test_event_2026.vxml'


def compiled_dashboard(reference=EVENT):
    strings = b'override-background\0' + reference.encode() + b'\0Untouched controls\0'
    packed = lz4(strings)
    header = bytearray(120)
    struct.pack_into('<I', header, 0, 0x4B563305)
    struct.pack_into('<I', header, 20, 1)
    struct.pack_into('<I', header, 28, len(strings))
    struct.pack_into('<I', header, 48, len(strings) + 6)
    struct.pack_into('<I', header, 52, len(packed) + 6)
    struct.pack_into('<II', header, 72, len(strings), len(packed))
    struct.pack_into('<II', header, 80, 6, 6)
    blocks = [(b'RED2', b'dependency fixture'), (b'DATA', b'\0' * 6),
              (b'LaCo', bytes(header) + packed + b'\x01\x02\x03\x04\x05\x06')]
    raw = bytearray(struct.pack('<IHHII', 0, 12, 3, 8, len(blocks)))
    raw.extend(b'\0' * (len(blocks) * 12))
    for i, (tag, data) in enumerate(blocks):
        raw.extend(b'\0' * (-len(raw) % 4))
        start = len(raw)
        at = 16 + i * 12
        struct.pack_into('<4sII', raw, at, tag, start - at - 4, len(data))
        raw.extend(data)
    struct.pack_into('<I', raw, 0, len(raw))
    return bytes(raw)


class SceneTests(unittest.TestCase):
    def test_patch_preserves_other_blocks_and_numeric_buffer(self):
        original = compiled_dashboard()
        result = patch_dashboard(original, EVENT)
        self.assertEqual(background_references(result), [CUSTOM_BACKGROUND])
        before, after = dict(resource_blocks(original)), dict(resource_blocks(result))
        self.assertEqual(before[b'RED2'], after[b'RED2'])
        self.assertEqual(before[b'DATA'], after[b'DATA'])
        strings, consumed, _ = kv3_strings_buffer(before[b'LaCo'])
        new_strings, new_consumed, _ = kv3_strings_buffer(after[b'LaCo'])
        self.assertEqual(new_strings, strings.replace(EVENT.encode(), CUSTOM_BACKGROUND.encode()))
        self.assertEqual(before[b'LaCo'][120 + consumed:], after[b'LaCo'][120 + new_consumed:])

    def test_ambiguous_or_unknown_reference_refused(self):
        with self.assertRaises(ValueError):
            patch_dashboard(compiled_dashboard(), 'panorama/layout/not_the_event.vxml')
        with self.assertRaises(ValueError):
            background_references(b'bad')

    def test_current_fix_uses_current_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            source = compiled_dashboard()
            write_vpk(game / 'dota/pak01_dir.vpk', {DASHBOARD: source, EVENT + '_c': compiled_dashboard()})
            files, report = current_fix(game)
            self.assertEqual(report['event_scene'], EVENT + '_c')
            self.assertEqual(report['source_sha256'], hashlib.sha256(source).hexdigest())
            self.assertEqual(background_references(files[DASHBOARD]), [CUSTOM_BACKGROUND])
            self.assertEqual(VPK(game / 'dota/pak01_dir.vpk').read(DASHBOARD), source)

    def test_event_name_resolved_from_localization(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            token = 'DOTA_MonsterHoard2026_TreasureTitle'
            write_vpk(game / 'dota/pak01_dir.vpk', {
                DASHBOARD: compiled_dashboard(),
                EVENT + '_c': compiled_dashboard('#' + token),
                'resource/localization/dota_english.txt': ('"' + token + '" "Trove of Terror"').encode('utf-16')})
            _, report = current_fix(game)
            self.assertEqual(report['event_name'], 'Trove of Terror')


class FontTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / 'game'
        self.font = self.game / 'dota/panorama/fonts/radiance-regular.otf'
        self.font.parent.mkdir(parents=True)
        self.font.write_bytes(b'original font fixture')
        self.storage = self.root / 'storage'
        closed = patch.object(core, 'ensure_game_closed')
        closed.start()
        self.addCleanup(closed.stop)

    def test_disable_restore_survives_restart(self):
        fonts = Fonts(self.game, self.storage)
        self.assertTrue(fonts.catalog()[0]['enabled'])
        fonts.toggle(self.font.name, False)
        self.assertFalse(self.font.exists())
        reloaded = Fonts(self.game, self.storage)
        self.assertFalse(reloaded.catalog()[0]['enabled'])
        reloaded.toggle(self.font.name, True)
        self.assertEqual(self.font.read_bytes(), b'original font fixture')
        self.assertTrue(reloaded.catalog()[0]['enabled'])

    def test_steam_update_and_traversal_not_overwritten(self):
        fonts = Fonts(self.game, self.storage)
        fonts.toggle(self.font.name, False)
        self.font.write_bytes(b'new Steam font')
        with self.assertRaisesRegex(ValueError, 'Steam'):
            fonts.toggle(self.font.name, True)
        self.assertEqual(self.font.read_bytes(), b'new Steam font')
        with self.assertRaises(ValueError):
            fonts.toggle('../escape.otf', False)

    def test_game_running_prevents_font_change(self):
        with patch.object(core, 'ensure_game_closed', side_effect=ValueError('running')):
            with self.assertRaises(ValueError):
                Fonts(self.game, self.storage).toggle(self.font.name, False)
        self.assertTrue(self.font.is_file())


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg unavailable')
class StudioFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / 'game'
        (self.game / 'dota').mkdir(parents=True)
        (self.game / 'dota/gameinfo.gi').write_text('fixture')
        (self.game / 'dota/cfg').mkdir()
        (self.game / 'dota/cfg/boot.vcfg').write_text('"boot" { "UILanguage" "english" "AudioLanguage" "english" }')
        (self.game / 'dota_russian').mkdir()
        (self.game / 'dota_russian/gameinfo.gi').write_text('fixture')
        write_vpk(self.game / 'dota/pak01_dir.vpk', {DASHBOARD: compiled_dashboard(), EVENT + '_c': compiled_dashboard()})
        self.source = self.root / 'input.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=96x64:d=0.4',
                        '-c:v', 'mpeg4', str(self.source)], check=True, timeout=30)
        self.library = Library(self.root / 'storage', self.game)
        self.library.template.mkdir(parents=True)
        write_vpk(self.library.template / 'pak01_dir.vpk', {CUSTOM_BACKGROUND + '_c': b'compiled video fixture',
                   'panorama/styles/dashboard_background_last_match.vcss_c': b'style fixture'})
        write_vpk(self.library.template / 'pak02_dir.vpk', {DASHBOARD: b'OLD DASHBOARD'})
        self.original = (self.game / 'dota/pak01_dir.vpk').read_bytes()
        closed = patch.object(core, 'ensure_game_closed')
        closed.start()
        self.addCleanup(closed.stop)
        steam = patch('dota_background.steam_options.configs', return_value=[])
        steam.start()
        self.addCleanup(steam.stop)

    def test_choose_mp4_convert_preview_library_apply_fix_disable(self):
        identifier = self.library.import_video(self.source)
        self.assertEqual(identifier, self.library.import_video(self.source))
        self.assertEqual(len(self.library.items()), 1)
        item_path = self.library.item_path(identifier)
        self.assertTrue((item_path / 'preview.jpg').is_file())
        events = []
        self.library.activate(identifier, (128, 72), lambda *event: events.append(event))
        self.assertEqual(self.library.active()[0], identifier)
        target, record = mounts.installation(self.game, verify=True)
        manifest = record['manifest']
        archive = VPK(target / next(iter(record['owned_files'])))
        video = item_path / 'check.webm'
        video.write_bytes(archive.read('123/123.webm'))
        checked = core.video_info(video)
        self.assertEqual((checked['width'], checked['height'], checked['codec']), (128, 72, 'vp9'))
        self.assertEqual(manifest['scene_fix']['event_scene'], EVENT + '_c')
        self.assertEqual(background_references(archive.read(DASHBOARD)), [CUSTOM_BACKGROUND])
        self.assertEqual((self.game / 'dota/pak01_dir.vpk').read_bytes(), self.original)
        self.assertEqual(events[-1][0], 100)
        # Repair must preserve video bytes and make a backup of the previous installation.
        video_before = archive.read('123/123.webm')
        repaired = self.library.repair_scene()
        self.assertTrue(Path(repaired['backup']).is_dir())
        target, record = mounts.installation(self.game, verify=True)
        self.assertEqual(VPK(target / next(iter(record['owned_files']))).read('123/123.webm'), video_before)
        mounts.disable(self.game)
        self.assertIsNone(self.library.active()[0])
        self.assertEqual(len(self.library.items()), 1)

    def test_conversion_failure_leaves_existing_background(self):
        identifier = self.library.import_video(self.source)
        self.library.activate(identifier, (128, 72))
        before = mounts.installation(self.game, verify=True)[1]
        with patch.object(media, 'convert', side_effect=ValueError('encoder failed')):
            with self.assertRaises(ValueError):
                self.library.activate(identifier, (256, 144))
        self.assertEqual(mounts.installation(self.game, verify=True)[1], before)


if __name__ == '__main__':
    unittest.main()
