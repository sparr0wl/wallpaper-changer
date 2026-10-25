"""Monitor detection, bounded WebM encoding, and still previews."""
from pathlib import Path
import json
import os
import shutil
import subprocess

from .core import video_info
from .runtime import process_options


def probe(path):
    executable = shutil.which('ffprobe')
    if not executable:
        raise ValueError('Установите FFmpeg: не найден ffprobe')
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Видеофайл не найден')
    result = subprocess.run([executable, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=30, **process_options())
    if result.returncode:
        raise ValueError('Не удалось прочитать видео: ' + result.stderr[-400:])
    info = json.loads(result.stdout)
    streams = [s for s in info.get('streams', []) if s.get('codec_type') == 'video']
    if not streams:
        raise ValueError('В файле нет видеодорожки')
    duration = float(info.get('format', {}).get('duration', streams[0].get('duration', 0)))
    if not 0 < duration <= 3600:
        raise ValueError('Выберите видео длительностью от 1 кадра до 1 часа')
    return {'width': streams[0]['width'], 'height': streams[0]['height'], 'duration': duration,
            'codec': streams[0].get('codec_name', ''), 'size': path.stat().st_size}


def monitors():
    try:
        result = subprocess.run(['hyprctl', '-j', 'monitors'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            found = []
            for monitor in json.loads(result.stdout):
                width, height = monitor['width'], monitor['height']
                if monitor.get('transform', 0) % 2:
                    width, height = height, width
                found.append({'name': monitor['name'], 'width': width, 'height': height,
                              'focused': monitor.get('focused', False)})
            return sorted(found, key=lambda m: not m['focused'])
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        pass
    try:
        screens = json.loads(os.environ.get('WALLPAPER_CHANGER_SCREENS', '[]'))
        found = []
        for screen in screens:
            width, height = valid_size((screen['width'], screen['height']))
            found.append({'name': str(screen['name']), 'width': width, 'height': height,
                          'focused': bool(screen.get('focused', False))})
        return sorted(found, key=lambda m: not m['focused'])
    except (ValueError, TypeError, KeyError):
        pass
    return []


def valid_size(size):
    width, height = map(int, size)
    if not (64 <= width <= 7680 and 64 <= height <= 7680):
        raise ValueError('Недопустимое разрешение видео')
    return width - width % 2, height - height % 2


def convert(source, destination, size, progress=None):
    executable = shutil.which('ffmpeg')
    if not executable:
        raise ValueError('Установите FFmpeg: не найден ffmpeg')
    source, destination = Path(source).resolve(), Path(destination)
    if destination.exists():
        raise ValueError('Файл конвертации уже существует')
    info = probe(source)
    width, height = valid_size(size)
    # Reserve ample container overhead below the guide's 20 MB recommendation.
    budget = 18_000_000
    bitrate = min(8_000_000, int(budget * 8 / info['duration'] * 0.90))
    if bitrate < 32_000:
        raise ValueError('Видео слишком длинное для фона до 20 МБ; выберите более короткий фрагмент')
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-i', str(source),
               '-map', '0:v:0', '-an', '-vf', f'scale={width}:{height}:flags=lanczos,setsar=1,fps=30',
               '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '6', '-row-mt', '1', '-threads', '4',
               '-pix_fmt', 'yuv420p', '-b:v', str(bitrate), '-maxrate', str(bitrate), '-bufsize', str(bitrate * 2),
               '-progress', 'pipe:1', '-nostats', str(destination)]
    try:
        # stderr goes to a bounded temporary file, avoiding pipe deadlocks.
        import tempfile
        with tempfile.TemporaryFile(mode='w+') as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True, **process_options())
            try:
                for line in process.stdout:
                    if line.startswith('out_time_us=') and progress:
                        try:
                            progress(min(95, int(int(line.split('=', 1)[1]) / 1e6 / info['duration'] * 95)))
                        except ValueError:
                            pass
                result = process.wait(timeout=30)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                process.stdout.close()
            if result:
                errors.seek(0)
                raise ValueError('Ошибка конвертации: ' + errors.read()[-800:])
        checked = video_info(destination)
        if checked['size'] > 20_000_000:
            raise ValueError('Результат превысил 20 МБ; выберите более короткое видео')
        if (checked['width'], checked['height']) != (width, height):
            raise ValueError('Не удалось подогнать разрешение')
        return checked
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def thumbnail(source, destination):
    executable = shutil.which('ffmpeg')
    if not executable:
        raise ValueError('Не найден ffmpeg')
    info = probe(source)
    subprocess.run([executable, '-v', 'error', '-nostdin', '-n', '-ss', str(min(1, info['duration'] / 3)),
                    '-i', str(source), '-frames:v', '1', '-vf', 'scale=640:360:force_original_aspect_ratio=increase,crop=640:360',
                    '-threads', '1', str(destination)], capture_output=True, check=True, timeout=45, **process_options())
