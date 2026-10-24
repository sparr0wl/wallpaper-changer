"""Tk desktop UI. Long-running operations never block the event loop."""
from pathlib import Path
import datetime
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from . import core, mounts
from .templates import download_template, import_zip
from .vpk import VPK


class App:
    def __init__(self, root):
        self.root = root
        root.title('Wallpaper changer')
        root.geometry('1080x790')
        root.minsize(850, 680)
        self.events = queue.Queue()
        self.buttons = []
        self.archive = None
        self.built = None
        self.preview = None
        self.busy = False
        self.storage = Path.home() / '.local/share/dota-background-changer'
        self.game = tk.StringVar()
        self.template = tk.StringVar()
        self.video = tk.StringVar()
        self.target = tk.StringVar()
        self.output = tk.StringVar(value=str(self.storage / 'packages' / self.stamp()))
        self.status = tk.StringVar(value='Выберите основу и WebM. Исходные файлы Dota не заменяются.')
        self.filter = tk.StringVar()
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('Sans', 22, 'bold'))
        style.configure('Accent.TButton', font=('Sans', 11, 'bold'), padding=8)
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Wallpaper changer', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Свой фон главного меню · WebM · VPK v1 / v2').pack(anchor='w', pady=(4, 15))
        tabs = ttk.Notebook(outer)
        tabs.pack(fill='both', expand=True)
        background = ttk.Frame(tabs, padding=15)
        archive = ttk.Frame(tabs, padding=15)
        help_tab = ttk.Frame(tabs, padding=15)
        tabs.add(background, text='  Фон меню  ')
        tabs.add(archive, text='  Просмотр VPK  ')
        tabs.add(help_tab, text='  Инструкция  ')
        background.columnconfigure(1, weight=1)
        self.row(background, 0, 'Папка Dota 2', self.game, self.choose_game)
        self.button(background, 'Найти игру', self.detect).grid(row=1, column=1, sticky='w', pady=(0, 10))
        self.row(background, 2, 'Основа / шаблон', self.template, self.choose_template)
        template_actions = ttk.Frame(background)
        template_actions.grid(row=3, column=1, sticky='w', pady=(0, 10))
        self.button(template_actions, 'Скачать основу', self.download).pack(side='left')
        self.button(template_actions, 'Импорт ZIP', self.import_archive).pack(side='left', padx=6)
        self.button(template_actions, 'Выбрать VPK', self.choose_template_file).pack(side='left')
        self.button(template_actions, 'Проверить основу', self.inspect_template).pack(side='left', padx=6)
        self.row(background, 4, 'Видео .webm', self.video, self.choose_video)
        video_actions = ttk.Frame(background)
        video_actions.grid(row=5, column=1, sticky='w', pady=(0, 10))
        self.button(video_actions, 'Проверить видео', self.inspect_video).pack(side='left')
        self.button(video_actions, 'Предпросмотр', self.play).pack(side='left', padx=6)
        ttk.Label(background, text='Видео внутри VPK').grid(row=6, column=0, sticky='w', padx=(0, 10))
        self.targets = ttk.Combobox(background, textvariable=self.target)
        self.targets.grid(row=6, column=1, columnspan=2, sticky='ew', pady=5)
        ttk.Label(background, text='Определяется по основе; для пустой основы из гайда — 123/123.webm.',
                  wraplength=680).grid(row=7, column=1, columnspan=2, sticky='w', pady=(0, 10))
        self.row(background, 8, 'Новая папка пакета', self.output, self.choose_output)
        actions = ttk.Frame(background)
        actions.grid(row=9, column=0, columnspan=3, sticky='w', pady=15)
        self.button(actions, '1. Собрать фон', self.build, 'Accent.TButton').pack(side='left')
        self.button(actions, '2. Установить', self.install, 'Accent.TButton').pack(side='left', padx=10)
        self.button(actions, 'Отключить фон', self.disable).pack(side='left')
        launch = ttk.LabelFrame(background, text='Параметры запуска Steam', padding=10)
        launch.grid(row=10, column=0, columnspan=3, sticky='ew')
        ttk.Label(launch, text='Не требуются', font=('Monospace', 14)).pack(side='left')
        self.button(launch, 'Проверить подключение', self.copy_launch).pack(side='left', padx=20)
        ttk.Label(launch, text='Используется штатная папка аудиоязыка').pack(side='left')
        ttk.Label(background, text='Метод меняет язык загрузки ресурсов; текст и озвучка могут стать английскими.\n'
                  'Совместимость основы с текущим патчем проверяется запуском игры.',
                  wraplength=900).grid(row=11, column=0, columnspan=3, sticky='w', pady=10)

        bar = ttk.Frame(archive)
        bar.pack(fill='x')
        self.button(bar, 'Открыть VPK', self.open_vpk).pack(side='left')
        self.button(bar, 'Извлечь выбранное', lambda: self.extract(True)).pack(side='left', padx=6)
        self.button(bar, 'Распаковать всё', lambda: self.extract(False)).pack(side='left')
        ttk.Label(bar, text='Поиск:').pack(side='left', padx=(15, 5))
        ttk.Entry(bar, textvariable=self.filter).pack(side='left', fill='x', expand=True)
        self.filter.trace_add('write', lambda *_: self.populate())
        self.archive_label = ttk.Label(archive, text='Откройте *_dir.vpk; соседние тома *_000.vpk должны лежать рядом.')
        self.archive_label.pack(anchor='w', pady=10)
        listing = ttk.Frame(archive)
        listing.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(listing, columns=('path', 'size'), show='headings', selectmode='extended')
        self.tree.heading('path', text='Путь в архиве')
        self.tree.heading('size', text='Размер, байт')
        self.tree.column('path', width=690)
        self.tree.column('size', width=120, anchor='e')
        scroll = ttk.Scrollbar(listing, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)

        instructions = ('1. Закройте Dota 2. Нажмите «Скачать основу» либо импортируйте ZIP готового фона.\n\n'
                        '2. Выберите своё видео .webm (VP8 / VP9, до 30 МБ). Для надёжности используйте '
                        'короткое видео до 20 МБ и разрешение игры. Программа проверит кодек через ffprobe.\n\n'
                        '3. Проверьте основу: найденный путь видео подставится автоматически. Если WebM '
                        'несколько, выберите нужное. Для основы без видео используется 123/123.webm.\n\n'
                        '4. Соберите фон, затем установите. В штатной папке аудиоязыка появится отдельный VPK '
                        'и манифест. Предыдущий пакет этой программы сохраняется в game/.dota-background-backups.\n\n'
                        '5. Дополнительные параметры запуска не нужны. Старый -language 123 удаляется. '
                        'Остальные параметры Steam сохраняются. Запустите игру.\n\n'
                        'Для возврата нажмите «Отключить фон» и перезапустите игру '
                        '(после восстановления аудиоязыка). Для восстановления сохранённого пакета '
                        'выберите его папку через «Выбрать собранный пакет» ниже и установите снова.\n\n'
                        'Оригинальные pak01 игры не редактируются. Чужие архивы и изменённые пакеты '
                        'автоматически не перезаписываются. Основа и фикс из старых гайдов могут требовать '
                        'обновления после патча. Программа не подтверждает совместимость до проверки в игре.')
        ttk.Label(help_tab, text=instructions, justify='left', wraplength=920).pack(anchor='w')
        links = ttk.Frame(help_tab)
        links.pack(anchor='w', pady=15)
        self.button(links, 'Исходный гайд', lambda: webbrowser.open(core.GUIDE)).pack(side='left')
        self.button(links, 'Выбрать собранный пакет', self.select_package).pack(side='left', padx=10)
        ttk.Label(outer, textvariable=self.status, wraplength=1000).pack(anchor='w', pady=(12, 6))
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x')
        self.log = tk.Text(outer, height=4, state='disabled', font=('Monospace', 9))
        self.log.pack(fill='x', pady=(7, 0))
        root.after(100, self.poll)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.detect()
        local_base = self.storage / 'templates/local-base'
        if local_base.is_dir():
            self.template.set(str(local_base))
            self.inspect_template()

    @staticmethod
    def stamp():
        return datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')

    def button(self, parent, text, command, style='TButton'):
        button = ttk.Button(parent, text=text, command=lambda: self.guard(command), style=style)
        self.buttons.append(button)
        return button

    def guard(self, command):
        try:
            command()
        except Exception as e:
            self.report(str(e), error=True)

    def row(self, parent, row, label, variable, browse):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=5)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky='ew', pady=5)
        self.button(parent, 'Обзор…', browse).grid(row=row, column=2, padx=(8, 0), pady=5)

    def report(self, text, error=False):
        self.status.set(text)
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')
        if error:
            messagebox.showerror('Wallpaper changer', text, parent=self.root)

    def work(self, label, operation, done):
        if self.busy:
            return
        self.busy = True
        self.status.set(label)
        self.progress.start()
        for b in self.buttons:
            b.configure(state='disabled')

        def worker():
            try:
                self.events.put((True, operation(), done))
            except Exception as e:
                self.events.put((False, str(e), done))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            success, value, done = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            for b in self.buttons:
                b.configure(state='normal')
            if success:
                self.guard(lambda: done(value))
            else:
                self.report(value, error=True)
        self.root.after(100, self.poll)

    def detect(self):
        found = core.discover_games()
        if found:
            self.game.set(str(found[0]))
            self.report('Dota 2 найдена: ' + str(found[0]))
        else:
            self.report('Dota 2 не найдена автоматически. Укажите папку вручную.')

    def choose_game(self):
        path = filedialog.askdirectory(title='Папка dota 2 beta или game')
        if path:
            self.game.set(str(core.game_directory(path)))

    def choose_template(self):
        path = filedialog.askdirectory(title='Папка с panorama и 123 либо VPK готового фона')
        if path:
            self.template.set(path)
            self.inspect_template()

    def choose_template_file(self):
        path = filedialog.askopenfilename(filetypes=[('Valve VPK', '*.vpk')])
        if path:
            self.template.set(path)
            self.inspect_template()

    def inspect_template(self):
        path = self.template.get()

        def done(packages):
            targets = core.video_targets(packages)
            self.targets.configure(values=targets or ['123/123.webm'])
            self.target.set(targets[0] if len(targets) == 1 else ('123/123.webm' if not targets else ''))
            self.report(f'Основа: {len(packages)} VPK, WebM: {len(targets)}. ' +
                        ('Выберите видео для замены.' if len(targets) > 1 else 'Можно собирать фон.'))
        self.work('Проверка основы…', lambda: core.load_template(path), done)

    def new_destination(self, title, category):
        directory = self.storage / category
        directory.mkdir(parents=True, exist_ok=True)
        return filedialog.asksaveasfilename(title=title, initialdir=directory, initialfile=self.stamp())

    def download(self):
        destination = self.new_destination('Новая папка для основы', 'templates')
        if destination:
            def done(result):
                path, warning = result
                self.template.set(str(path))
                self.target.set('123/123.webm')
                self.report(warning or 'Основа и фикс загружены. Выберите WebM и соберите фон.')
            self.work('Загрузка основы и фикса из авторского гайда…', lambda: download_template(destination), done)

    def import_archive(self):
        path = filedialog.askopenfilename(filetypes=[('ZIP', '*.zip')])
        if path:
            destination = self.new_destination('Новая папка для импорта', 'templates')
            if destination:
                def done(result):
                    self.template.set(str(result))
                    self.report('ZIP импортирован: ' + str(result))
                    self.inspect_template()
                self.work('Импорт ZIP…', lambda: import_zip(path, destination), done)

    def choose_video(self):
        path = filedialog.askopenfilename(filetypes=[('WebM', '*.webm'), ('Все файлы', '*')])
        if path:
            self.video.set(path)
            self.inspect_video()

    def inspect_video(self):
        video = self.video.get()
        self.work('Проверка WebM…', lambda: core.video_info(video),
                  lambda info: self.report(f"Видео: {info['width']}×{info['height']}, {info['codec']}, "
                                           f"{info['duration']} с, {info['size'] / 1e6:.1f} МБ"))

    def play(self):
        video = Path(self.video.get()).resolve()
        if not video.is_file():
            raise ValueError('Выберите видео')
        player = shutil.which('ffplay')
        if not player:
            raise ValueError('Для предпросмотра установите ffplay из FFmpeg')
        if self.preview and self.preview.poll() is None:
            self.preview.terminate()
        self.preview = subprocess.Popen([player, '-loglevel', 'error', '-an', '-loop', '0', '-x', '800', '-i', str(video)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def choose_output(self):
        path = self.new_destination('Новая папка для собранного пакета', 'packages')
        if path:
            self.output.set(path)

    def build(self):
        template, video, output, target = self.template.get(), self.video.get(), self.output.get(), self.target.get()

        def done(result):
            self.built = Path(output)
            self.report('Пакет проверен и собран: ' + output + '. Теперь нажмите «Установить».')
            self.output.set(str(self.storage / 'packages' / self.stamp()))
        self.work('Сборка VPK и проверка CRC32…', lambda: core.build_background(template, video, output, target or None), done)

    def select_package(self):
        path = filedialog.askdirectory(title='Собранный пакет или его резервная копия')
        if path:
            core.check_package(path)
            self.built = Path(path)
            self.report('Выбран пакет: ' + path + '. Нажмите «Установить».')

    def install(self):
        if not self.built:
            raise ValueError('Сначала соберите фон или выберите готовый пакет во вкладке «Инструкция»')
        package, game = self.built, self.game.get()

        def done(result):
            target, backup = result
            text = f'Установлено: {target}. Дополнительные параметры запуска не нужны.'
            if backup:
                text += f' Предыдущий пакет: {backup}'
            self.report(text)
        def operation():
            from .steam_options import remove_obsolete
            result = mounts.install(package, game)
            remove_obsolete(self.storage)
            return result
        self.work('Установка фона…', operation, done)

    def disable(self):
        game = self.game.get()
        self.work('Сохранение и отключение фона…', lambda: mounts.disable(game),
                  lambda backup: self.report(f'Фон отключён и сохранён: {backup}. Аудиоязык восстановлен.'))

    def copy_launch(self):
        status = mounts.language_status(core.game_directory(self.game.get()))
        self.report(f'Аудиоязык: {status["audio"]}. Папка загрузки: {status["folder"] or "нужна установка"}')

    def open_vpk(self):
        path = filedialog.askopenfilename(filetypes=[('Valve VPK', '*.vpk')])
        if path:
            def done(archive):
                self.archive = archive
                self.archive_label.configure(text=f'{archive.path.name} · VPK {archive.version} · {len(archive.entries):,} файлов')
                self.populate()
                self.report('Архив открыт. Для больших архивов список ограничен 5000 строками; используйте поиск.')
            self.work('Чтение дерева VPK…', lambda: VPK(path), done)

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        if self.archive:
            query = self.filter.get().casefold()
            count = 0
            for name, entry in self.archive.entries.items():
                if query in name.casefold():
                    self.tree.insert('', 'end', values=(name, entry.size))
                    count += 1
                    if count >= 5000:
                        break

    def extract(self, selected):
        if not self.archive:
            raise ValueError('Сначала откройте VPK')
        names = [self.tree.item(item, 'values')[0] for item in self.tree.selection()] if selected else None
        if selected and not names:
            raise ValueError('Выберите файлы в списке')
        destination = filedialog.askdirectory(title='Куда распаковать? Существующие файлы не перезаписываются')
        if destination:
            archive = self.archive
            self.work('Извлечение с проверкой CRC32…', lambda: archive.extract(destination, names),
                      lambda _: self.report('Файлы извлечены: ' + destination))

    def close(self):
        if self.busy:
            self.report('Дождитесь завершения операции перед закрытием.')
            return
        if self.preview and self.preview.poll() is None:
            self.preview.terminate()
        self.root.destroy()


def run():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise ValueError(f'Не удалось открыть графическое окно: {e}. Запустите приложение из терминала графической сессии.') from e
    App(root)
    root.mainloop()
