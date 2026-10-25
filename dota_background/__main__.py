import argparse
import json
import subprocess
import sys
import zipfile

from . import core
from .vpk import VPK, write_vpk


def main():
    parser = argparse.ArgumentParser(description='Dota Background Changer — WebM и VPK')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('gui', help='Открыть графическое приложение')
    commands.add_parser('detect', help='Найти Dota 2')
    p = commands.add_parser('list', help='Показать содержимое VPK')
    p.add_argument('archive')
    p.add_argument('--filter', default='')
    p = commands.add_parser('extract', help='Распаковать VPK без перезаписи файлов')
    p.add_argument('archive')
    p.add_argument('output')
    p.add_argument('--entry', action='append', help='Извлечь только указанный путь; можно повторять')
    p = commands.add_parser('pack', help='Собрать VPK из папки')
    p.add_argument('folder')
    p.add_argument('output')
    p = commands.add_parser('probe', help='Проверить WebM')
    p.add_argument('video')
    p = commands.add_parser('build', help='Заменить видео в шаблоне и собрать фон')
    p.add_argument('--template', required=True)
    p.add_argument('--video', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--target', help='Путь видео внутри VPK')
    p.add_argument('--game', help='Папка игры: автоматически собрать актуальный фикс события')
    p = commands.add_parser('install', help='Установить собранный пакет')
    p.add_argument('package')
    p.add_argument('--game', required=True)
    p = commands.add_parser('disable', help='Убрать установленный фон в резервную копию')
    p.add_argument('--game', required=True)
    p = commands.add_parser('download-template', help='Скачать основу из авторских гайдов')
    p.add_argument('output')
    p = commands.add_parser('scene', help='Определить сцену текущего события и проверить фикс')
    p.add_argument('--game', required=True)
    p = commands.add_parser('repair-scene', help='Обновить фикс установленного фона, сохранив его видео')
    p.add_argument('--game', required=True)
    p = commands.add_parser('convert', help='Конвертировать видео в WebM с растяжением под экран')
    p.add_argument('video')
    p.add_argument('output')
    p.add_argument('--width', type=int, default=1920)
    p.add_argument('--height', type=int, default=1080)
    p = commands.add_parser('import-zip', help='Импортировать ZIP готового фона')
    p.add_argument('archive')
    p.add_argument('output')
    args = parser.parse_args()
    try:
        if args.command in (None, 'gui'):
            from .desktop import run
            run()
        elif args.command == 'detect':
            print('\n'.join(map(str, core.discover_games())) or 'Dota 2 не найдена')
        elif args.command == 'list':
            vpk = VPK(args.archive)
            for name, entry in vpk.entries.items():
                if args.filter.casefold() in name.casefold():
                    print(f'{entry.size:12d}  {name}')
        elif args.command == 'extract':
            VPK(args.archive).extract(args.output, args.entry)
            print('Извлечено в ' + args.output)
        elif args.command == 'pack':
            from pathlib import Path
            root = Path(args.folder).resolve()
            output = Path(args.output).resolve()
            if not root.is_dir() or output.exists() or output.is_relative_to(root):
                raise ValueError('Нужны существующая папка и новый VPK вне этой папки')
            files = {}
            total = 0
            for item in sorted(root.rglob('*')):
                if item.is_symlink():
                    raise ValueError('Ссылки не поддерживаются')
                if item.is_file():
                    total += item.stat().st_size
                    if total > core.MAX_TEMPLATE:
                        raise ValueError('Папка больше 256 МиБ')
                    files[item.relative_to(root).as_posix()] = item.read_bytes()
            write_vpk(output, files)
            print(output)
        elif args.command == 'probe':
            print(json.dumps(core.video_info(args.video), ensure_ascii=False, indent=2))
        elif args.command == 'build':
            result = core.build_background(args.template, args.video, args.output, args.target, scene_game=args.game)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == 'install':
            from .mounts import install
            from .steam_options import remove_obsolete
            from pathlib import Path
            target, backup = install(args.package, args.game)
            remove_obsolete(Path.home() / '.local/share/dota-background-changer')
            print(f'Установлено: {target}\nРезервная копия: {backup}\nДополнительные параметры запуска не нужны.')
        elif args.command == 'disable':
            from .mounts import disable
            print(f'Фон сохранён: {disable(args.game)}\nПрежний аудиоязык восстановлен.')
        elif args.command == 'download-template':
            from .templates import download_template
            destination, warning = download_template(args.output)
            print(destination)
            if warning:
                print(warning, file=sys.stderr)
        elif args.command == 'import-zip':
            from .templates import import_zip
            print(import_zip(args.archive, args.output))
        elif args.command == 'scene':
            from .scene import current_fix
            _, report = current_fix(core.game_directory(args.game))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == 'repair-scene':
            from .library import Library
            print(json.dumps(Library(game=args.game).repair_scene(), ensure_ascii=False, indent=2))
        elif args.command == 'convert':
            from .media import convert
            print(json.dumps(convert(args.video, args.output, (args.width, args.height)), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TimeoutError, subprocess.TimeoutExpired, zipfile.BadZipFile) as e:
        print(f'Ошибка: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
