from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dota_background.locking import app_lock
from dota_background.runtime import data_directory
from dota_background.library import Library, write_json
from dota_background import media


class RuntimeTests(unittest.TestCase):
    def test_qt_monitors_fallback_uses_physical_primary_screen(self):
        screens = '[{"name":"secondary","width":1920,"height":1080}, {"name":"primary","width":3840,"height":2160,"focused":true}]'
        with patch.dict(os.environ, {'WALLPAPER_CHANGER_SCREENS': screens}):
            with patch('dota_background.media.subprocess.run', side_effect=FileNotFoundError):
                self.assertEqual(media.monitors()[0]['name'], 'primary')
                self.assertEqual(media.monitors()[0]['width'], 3840)

    def test_storage_override_preserves_explicit_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {'DOTA_BACKGROUND_STORAGE': temporary}):
                self.assertEqual(data_directory(), Path(temporary))

    def test_backend_lock_excludes_a_second_process_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / '.app.lock'
            code = '''import sys
from dota_background.locking import app_lock
try:
    with app_lock(sys.argv[1]):
        pass
except BlockingIOError:
    sys.exit(17)
'''
            with app_lock(lock):
                result = subprocess.run([sys.executable, '-c', code, str(lock)], capture_output=True)
                self.assertEqual(result.returncode, 17, result.stderr)
            result = subprocess.run([sys.executable, '-c', code, str(lock)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_saved_game_path_does_not_prevent_opening_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / 'settings.json', {'game': str(root / 'removed-game')})
            library = Library(root)
            self.assertIsNone(library.game)
            self.assertEqual(library.items(), [])


if __name__ == '__main__':
    unittest.main()
