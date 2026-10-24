from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dota_background import core, mounts
from dota_background.library import write_json
from dota_background.steam_options import launch_option_span, remove_obsolete
from dota_background.vpk import VPK, write_vpk


class MountedInstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / 'game'
        self.boot = self.game / 'dota/cfg/boot.vcfg'
        self.boot.parent.mkdir(parents=True)
        self.boot.write_bytes(b'"boot"\r\n{\r\n "UILanguage" "russian"\r\n "AudioLanguage" "russian"\r\n}\r\n')
        (self.game / 'dota/gameinfo.gi').write_text('game')
        self.folder = self.game / 'dota_russian'
        self.folder.mkdir()
        (self.folder / 'gameinfo.gi').write_bytes(b'original language gameinfo')
        write_vpk(self.folder / 'pak01_dir.vpk', {'sounds/voice.vsnd_c': b'voice'})
        self.package = self.root / 'package'
        write_vpk(self.package / 'pak01_dir.vpk', {'123/123.webm': b'video'})
        write_vpk(self.package / 'pak02_dir.vpk', {'panorama/layout/dashboard.vxml_c': b'fixed dashboard'})
        write_json(self.package / core.MARKER, {'app': core.APP_ID, 'video_path': '123/123.webm',
                   'files': {p.name: mounts.digest(p) for p in self.package.glob('*.vpk')}})
        self.closed = patch.object(core, 'ensure_game_closed')
        self.closed.start()
        self.addCleanup(self.closed.stop)

    def test_real_language_mount_preserves_voice_and_reverts_audio(self):
        original = self.boot.read_bytes()
        voice = (self.folder / 'pak01_dir.vpk').read_bytes()
        target, _ = mounts.install(self.package, self.game)
        self.assertEqual(target.name, 'pak30_dir.vpk')
        self.assertEqual(mounts.language_status(self.game)['audio'], 'russian')
        self.assertEqual(mounts.language_status(self.game)['ui'], 'russian')
        self.assertEqual(VPK(target).read('123/123.webm'), b'video')
        self.assertEqual(VPK(target).read('panorama/layout/dashboard.vxml_c'), b'fixed dashboard')
        self.assertEqual((self.folder / 'pak01_dir.vpk').read_bytes(), voice)
        self.assertEqual((self.folder / 'gameinfo.gi').read_bytes(), b'original language gameinfo')
        backup = mounts.disable(self.game)
        self.assertTrue((backup / 'pak30_dir.vpk').is_file())
        self.assertEqual(self.boot.read_bytes(), original)
        self.assertTrue((self.folder / 'pak01_dir.vpk').is_file())

    def test_free_slots_and_conflicting_other_mod(self):
        write_vpk(self.folder / 'pak30_dir.vpk', {'unrelated.txt': b'other mod'})
        target, _ = mounts.install(self.package, self.game)
        self.assertEqual(target.name, 'pak31_dir.vpk')
        self.assertEqual(VPK(self.folder / 'pak30_dir.vpk').read('unrelated.txt'), b'other mod')
        write_vpk(self.folder / 'pak32_dir.vpk', {'panorama/layout/dashboard.vxml_c': b'conflicting mod'})
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Другой архив'):
            mounts.install(self.package, self.game)
        self.assertEqual(target.read_bytes(), before)

    def test_english_speech_uses_empty_layer_not_installed_russian_voices(self):
        self.boot.write_text('"boot" { "UILanguage" "english" "AudioLanguage" "english" }')
        chinese = self.game / 'dota_schinese'
        chinese.mkdir()
        (chinese / 'gameinfo.gi').write_text('official fixture')
        target, _ = mounts.install(self.package, self.game)
        self.assertEqual(target.parent, chinese)
        self.assertEqual(mounts.language_status(self.game)['ui'], 'english')
        self.assertEqual(mounts.language_status(self.game)['audio'], 'schinese')
        self.assertTrue((self.folder / 'pak01_dir.vpk').is_file())
        mounts.disable(self.game)
        self.assertEqual(mounts.language_status(self.game)['audio'], 'english')

    def test_boot_write_failure_restores_previous_package(self):
        target, _ = mounts.install(self.package, self.game)
        before = target.read_bytes()
        with patch.object(mounts, 'atomic', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                mounts.install(self.package, self.game)
        self.assertEqual(target.read_bytes(), before)
        mounts.installation(self.game, verify=True)


class SteamOptionsTests(unittest.TestCase):
    def test_only_dota_launch_options_changed_not_tickets_or_other_apps(self):
        text = '''"UserLocalConfigStore" { "apptickets" { "570" "PRIVATE-FIXTURE" }
"Software" { "Valve" { "Steam" { "apps" {
"570" { "LaunchOptions" "+fps_max 120 -language 123 -novid" }
"730" { "LaunchOptions" "-language 123" }
} } } } }'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'localconfig.vdf'
            config.write_text(text)
            with patch('dota_background.steam_options.configs', return_value=[config]):
                self.assertEqual(len(remove_obsolete(root / 'data')), 1)
                changed = config.read_text()
                self.assertEqual(launch_option_span(changed)[2], '+fps_max 120  -novid')
                self.assertIn('"570" "PRIVATE-FIXTURE"', changed)
                self.assertIn('"730" { "LaunchOptions" "-language 123" }', changed)
                backups = list((root / 'data/steam-launch-backups').glob('*.json'))
                self.assertEqual(len(backups), 1)
                self.assertNotIn('PRIVATE-FIXTURE', backups[0].read_text())
                self.assertEqual(remove_obsolete(root / 'data'), [])

    def test_absent_or_duplicate_setting_is_not_guessed(self):
        self.assertIsNone(launch_option_span('"apps" { "570" { "LastPlayed" "1" } }'))
        with self.assertRaises(ValueError):
            launch_option_span('"apps" { "570" { "LaunchOptions" "a" "LaunchOptions" "b" } }')
