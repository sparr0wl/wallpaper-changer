"""Linux interface using the system GTK/Pango font stack."""
from pathlib import Path
import datetime
import shutil
import subprocess
import threading

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

from . import core, mounts
from .templates import download_template, import_zip
from .vpk import VPK


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.dota.background.changer')
        self.connect('activate', self.activate)
        self.storage = Path.home() / '.local/share/dota-background-changer'
        self.buttons = []
        self.busy = False
        self.built = None
        self.archive = None
        self.preview = None

    def activate(self, *_):
        if self.get_active_window():
            self.get_active_window().present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title='Фон главного меню Dota 2')
        self.css = Gtk.CssProvider()
        self.css.load_from_data(b'window { font-family: "Noto Sans", sans-serif; font-size: 14px; }')
        Gtk.StyleContext.add_provider_for_display(self.window.get_display(), self.css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window.set_default_size(1050, 820)
        self.window.connect('close-request', self.close)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(outer, 'set_margin_' + side)(18)
        self.window.set_child(outer)
        title = Gtk.Label(label='Фон главного меню Dota 2', xalign=0)
        title.add_css_class('title-1')
        outer.append(title)
        outer.append(Gtk.Label(label='Видео WebM · Сборка и распаковка VPK · Резервные копии', xalign=0))
        tabs = Gtk.Notebook(vexpand=True)
        outer.append(tabs)
        background = self.page(tabs, 'Фон меню')
        games = core.discover_games()
        self.game = self.row(background, 'Папка игры', str(games[0]) if games else '', 'folder')
        local = self.storage / 'templates/local-base'
        self.template = self.row(background, 'Основа фона', str(local) if local.is_dir() else '', 'folder')
        self.actions(background, [('Выбрать VPK', self.choose_template), ('Импорт ZIP', self.import_template),
                                  ('Скачать основу', self.download), ('Проверить основу', self.inspect_template)])
        self.video = self.row(background, 'Видео .webm', '', 'video')
        self.actions(background, [('Проверить видео', self.inspect_video), ('Предпросмотр', self.play)])
        self.target = self.row(background, 'Путь видео внутри VPK', '123/123.webm')
        background.append(Gtk.Label(label='Если в основе несколько WebM, укажите нужный путь из результата проверки.',
                                    xalign=0, wrap=True))
        self.output = self.row(background, 'Новая папка пакета', str(self.storage / 'packages' / self.stamp()))
        self.actions(background, [('1. Собрать фон', self.build), ('2. Установить', self.install),
                                  ('Отключить фон', self.disable), ('Выбрать готовый пакет', self.select_package)])
        self.actions(background, [('Проверить подключение', self.copy_launch)])
        background.append(Gtk.Label(label='Параметры запуска не нужны. Используется штатная папка аудиоязыка.\n'
                                    'Метод может переключить язык игры на английский. Совместимость основы проверяется в игре.',
                                    xalign=0, wrap=True))
        archive = self.page(tabs, 'Просмотр VPK')
        self.archive_path = self.row(archive, 'Архив', '', 'vpk')
        self.query = self.row(archive, 'Поиск по пути')
        self.entry = self.row(archive, 'Путь для извлечения')
        self.actions(archive, [('Открыть / найти', self.open_archive), ('Извлечь указанный файл', lambda: self.extract(True)),
                               ('Распаковать всё', lambda: self.extract(False))])
        self.listing = Gtk.TextView(editable=False, monospace=True, vexpand=True)
        self.listing.set_wrap_mode(Gtk.WrapMode.NONE)
        scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=220)
        scroller.set_child(self.listing)
        archive.append(scroller)
        help_page = self.page(tabs, 'Инструкция')
        help_page.append(Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True, label=
            '1. Закройте Dota 2. Локальная основа из wftrmaked.rar подставляется автоматически.\n\n'
            '2. Выберите WebM с кодеком VP8 или VP9. Рекомендуется короткое видео до 20 МБ '
            'с разрешением игры; программа принимает файлы до 30 МБ.\n\n'
            '3. Нажмите «Проверить основу». Путь единственного WebM определится автоматически. '
            'Если видео несколько, скопируйте нужный путь из результата проверки.\n\n'
            '4. Нажмите «Собрать фон», затем «Установить». Не добавляйте -language 123 в параметры '
            'запуска Steam, сохранив остальные параметры. Если -language уже есть, замените его значение.\n\n'
            '5. Для возврата нажмите «Отключить фон» и перезапустите игру '
            'либо верните прежнее значение языка.\n\n'
            'Пакеты устанавливаются в штатную папку аудиоязыка. Предыдущие пакеты этой программы '
            'сохраняются в game/.dota-background-backups. Для восстановления выберите папку копии '
            'кнопкой «Выбрать готовый пакет» и установите её снова.\n\n'
            'Оригинальные файлы Dota не редактируются. Чужие папки и изменённые пакеты '
            'не перезаписываются. Старые основы могут требовать обновления после патчей.\n\n'
            'Для просмотра большого VPK используйте поиск. Список ограничен 5000 строками. '
            'Для извлечения одного файла скопируйте его путь в соответствующее поле. '
            'Открывайте *_dir.vpk; соседние тома должны лежать рядом.'))
        self.status = Gtk.Label(label='Выберите видео и соберите фон.', xalign=0, wrap=True, selectable=True)
        outer.append(self.status)
        self.progress = Gtk.Spinner()
        outer.append(self.progress)
        self.log = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        log_scroll = Gtk.ScrolledWindow(min_content_height=80, max_content_height=130)
        log_scroll.set_child(self.log)
        outer.append(log_scroll)
        self.window.present()

    @staticmethod
    def stamp():
        return datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')

    def page(self, tabs, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(12)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(box)
        tabs.append_page(scroll, Gtk.Label(label=title))
        return box

    def row(self, parent, label, value='', chooser=None):
        row = Gtk.Box(spacing=10)
        row.append(Gtk.Label(label=label, xalign=0, width_chars=24))
        entry = Gtk.Entry(text=value, hexpand=True)
        row.append(entry)
        if chooser:
            self.button(row, 'Обзор…', lambda: self.choose(chooser, entry.set_text))
        parent.append(row)
        return entry

    def button(self, parent, text, action):
        button = Gtk.Button(label=text)
        button.connect('clicked', lambda *_: self.guard(action))
        parent.append(button)
        self.buttons.append(button)

    def actions(self, parent, actions):
        box = Gtk.Box(spacing=8)
        for text, action in actions:
            self.button(box, text, action)
        parent.append(box)

    def guard(self, action):
        try:
            action()
        except Exception as e:
            self.report('Ошибка: ' + str(e))

    def report(self, message):
        self.status.set_text(message)
        buffer = self.log.get_buffer()
        buffer.insert(buffer.get_end_iter(), message + '\n')

    def choose(self, kind, done):
        folder = kind == 'folder'
        dialog = Gtk.FileChooserNative.new('Выберите папку' if folder else 'Выберите файл', self.window,
                Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.OPEN, 'Выбрать', 'Отмена')
        if not folder:
            file_filter = Gtk.FileFilter()
            extension = {'video': 'webm', 'vpk': 'vpk', 'zip': 'zip'}[kind]
            file_filter.set_name(extension.upper())
            file_filter.add_pattern('*.' + extension)
            dialog.add_filter(file_filter)

        def response(widget, result):
            if result == Gtk.ResponseType.ACCEPT:
                path = widget.get_file().get_path()
                if path:
                    self.guard(lambda: done(path))
            widget.destroy()
        dialog.connect('response', response)
        dialog.show()

    def work(self, message, operation, done):
        if self.busy:
            return
        self.busy = True
        self.status.set_text(message)
        self.progress.start()
        for button in self.buttons:
            button.set_sensitive(False)

        def finish(value, error):
            self.busy = False
            self.progress.stop()
            for button in self.buttons:
                button.set_sensitive(True)
            if error:
                self.report('Ошибка: ' + error)
            else:
                self.guard(lambda: done(value))
            return False

        def worker():
            try:
                value = operation()
            except Exception as e:
                GLib.idle_add(finish, None, str(e))
            else:
                GLib.idle_add(finish, value, None)
        threading.Thread(target=worker, daemon=True).start()

    def choose_template(self):
        self.choose('vpk', self.template.set_text)

    def inspect_template(self):
        path = self.template.get_text()

        def done(packages):
            targets = core.video_targets(packages)
            if len(targets) <= 1:
                self.target.set_text(targets[0] if targets else '123/123.webm')
            else:
                self.target.set_text('')
            self.report(f'Архивов: {len(packages)}. Видео: ' + (', '.join(targets) or 'будет добавлено 123/123.webm'))
        self.work('Проверка основы…', lambda: core.load_template(path), done)

    def download(self):
        destination = self.storage / 'templates' / self.stamp()

        def done(result):
            path, warning = result
            self.template.set_text(str(path))
            self.report(warning or 'Основа загружена.')
        self.work('Загрузка основы…', lambda: download_template(destination), done)

    def import_template(self):
        def selected(path):
            destination = self.storage / 'templates' / self.stamp()

            def done(value):
                self.template.set_text(str(value))
                self.inspect_template()
            self.work('Импорт ZIP…', lambda: import_zip(path, destination), done)
        self.choose('zip', selected)

    def inspect_video(self):
        path = self.video.get_text()
        self.work('Проверка видео…', lambda: core.video_info(path),
                  lambda info: self.report(f"{info['width']}×{info['height']}, {info['codec']}, "
                                           f"{info['duration']} с, {info['size'] / 1e6:.1f} МБ"))

    def play(self):
        path = Path(self.video.get_text()).resolve()
        player = shutil.which('ffplay')
        if not path.is_file() or not player:
            raise ValueError('Выберите видео и убедитесь, что ffplay установлен')
        if self.preview and self.preview.poll() is None:
            self.preview.terminate()
        self.preview = subprocess.Popen([player, '-loglevel', 'error', '-an', '-loop', '0', '-x', '800', '-i', str(path)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def build(self):
        template, video, output, target = [entry.get_text() for entry in (self.template, self.video, self.output, self.target)]

        def done(_):
            self.built = Path(output)
            self.output.set_text(str(self.storage / 'packages' / self.stamp()))
            self.report('Фон собран: ' + output + '. Нажмите «Установить».')
        self.work('Сборка и проверка VPK…', lambda: core.build_background(template, video, output, target or None), done)

    def select_package(self):
        def selected(path):
            core.check_package(path)
            self.built = Path(path)
            self.report('Выбран пакет: ' + path)
        self.choose('folder', selected)

    def install(self):
        if not self.built:
            raise ValueError('Сначала соберите или выберите готовый пакет')
        package, game = self.built, self.game.get_text()
        def operation():
            from .steam_options import remove_obsolete
            result = mounts.install(package, game)
            remove_obsolete(self.storage)
            return result
        self.work('Установка…', operation,
                  lambda result: self.report(f'Установлено: {result[0]}. Предыдущая копия: {result[1] or "нет"}. '
                                             'Дополнительные параметры запуска не нужны.'))

    def disable(self):
        game = self.game.get_text()
        self.work('Отключение…', lambda: mounts.disable(game),
                  lambda backup: self.report(f'Фон отключён, копия: {backup}. Аудиоязык восстановлен.'))

    def copy_launch(self):
        status = mounts.language_status(core.game_directory(self.game.get_text()))
        self.report(f'Аудиоязык: {status["audio"]}. Папка загрузки: {status["folder"] or "нужна установка"}')

    def open_archive(self):
        path, query = self.archive_path.get_text(), self.query.get_text().casefold()

        def done(archive):
            self.archive = archive
            lines = []
            for name, entry in archive.entries.items():
                if query in name.casefold():
                    lines.append(f'{name}    [{entry.size} байт]')
                    if len(lines) == 5000:
                        break
            self.listing.get_buffer().set_text('\n'.join(lines))
            self.report(f'VPK {archive.version}: {len(archive.entries)} файлов; показано {len(lines)}.')
        self.work('Чтение VPK…', lambda: VPK(path), done)

    def extract(self, selected):
        if self.archive is None:
            raise ValueError('Сначала откройте архив')
        names = [self.entry.get_text().strip()] if selected else None
        archive = self.archive
        if selected and names[0] not in archive.entries:
            raise ValueError('Укажите точный путь файла из архива')

        def selected_folder(path):
            self.work('Извлечение…', lambda: archive.extract(path, names), lambda _: self.report('Извлечено в ' + path))
        self.choose('folder', selected_folder)

    def close(self, *_):
        if self.busy:
            self.report('Дождитесь завершения операции.')
            return True
        if self.preview and self.preview.poll() is None:
            self.preview.terminate()
        return False


def run():
    if not Gtk.init_check():
        raise ValueError('Нет доступа к графическому дисплею. Запустите программу в терминале рабочего стола.')
    App().run([])
