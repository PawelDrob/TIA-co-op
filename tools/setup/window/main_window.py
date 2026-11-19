"""The setup window: the pages of the first run, then the settings. It draws the rows of model.py and runs their actions
off the window's thread; every read and change goes through setup.py, the viewer's register.py or the dashboards."""
import dataclasses
import queue
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, ttk

from tools.setup.window import dashboards as dash
from tools.setup.window import model
from tools.setup.window import viewer

TITLE = 'TIA-co-op setup'
WIDTH, HEIGHT = 900, 680
TEXT_WIDTH = 600
PUMP_MS, TYPING_MS = 50, 300
BACKGROUND, CARD = '#f6f7f9', '#ffffff'
MARKS = {'ok': ('✔', '#007800'), 'todo': ('●', '#b06000'), 'missing': ('✖', '#b22222'), 'warning': ('!', '#b06000'),
         'info': ('·', '#808080')}
GRAY, BAD = '#606060', '#b22222'


@dataclasses.dataclass
class Context:
    """What the window works on: setup.py as a module, where the viewer registers, the dashboards' ports, the record of
    the first run. A test or a check gives its own."""
    setup: object
    first_run: model.FirstRun
    viewer_keys: tuple = ()          # (classes, choice) under HKEY_CURRENT_USER; () for the real ones
    ports: tuple = None              # (development, TIA); None for the defaults


class SetupWindow(tk.Tk):
    def __init__(self, context, page=None):
        super().__init__()
        self.context = context
        self.setup = context.setup
        self.clone = str(self.setup.CLONE)
        self.boards = dash.dashboards(context.ports)
        self.look = None
        # an index of model.PAGES, None for the settings: the first run until it is finished, then the settings
        self.page = page if page is not None else model.first_page(context.first_run, self.clone)
        self.details = {}           # row key: (failed, text) of its last action, until Refresh
        self.busy = ''
        self.results = queue.Queue()
        self.folder = tk.StringVar(self)
        self.folder.trace_add('write', lambda *_: self._folder_typed())
        self.typing = None
        self.scale = self.winfo_fpixels('1i') / 96
        self.title(TITLE)
        self._styles()
        self._layout()
        self.minsize(self.px(720), self.px(480))
        self.geometry('%dx%d+%d+%d' % (self.px(WIDTH), self.px(HEIGHT), max(0, (self.winfo_screenwidth() - self.px(WIDTH)) // 2),
                                       max(0, (self.winfo_screenheight() - self.px(HEIGHT)) // 2)))
        self.after(PUMP_MS, self._pump)
        self.reload()

    def px(self, pixels):
        """A size given for a screen at 100%, on this one."""
        return int(pixels * self.scale)

    # --- reading and acting, off the window's thread ---

    def work(self, label, job, then):
        """Runs job on a thread of its own; then(result) on the window's thread. One at a time: the buttons wait."""
        self.busy = label
        self._render()

        def run():
            try:
                result = job()
            except Exception as e:      # a failure shows in the window, never ends it
                result = e
            self.results.put((then, result))
        threading.Thread(target=run, daemon=True).start()

    def _pump(self):
        try:
            while True:
                then, result = self.results.get_nowait()
                self.busy = ''
                then(result)
        except queue.Empty:
            pass
        self.after(PUMP_MS, self._pump)

    def read_look(self):
        keys = self.context.viewer_keys
        return model.read(self.setup, lambda: viewer.state(*keys), lambda: [(d, dash.probe(d)) for d in self.boards])

    def reload(self, clear=False):
        if clear:
            self.details = {}
        self.work('Reading what is set up…', self.read_look, self._read)

    def _read(self, look):
        if isinstance(look, Exception):
            self.look = None
            self.details['read'] = (True, f'Reading failed: {look}')
        else:
            self.look = look
            self.details.pop('read', None)
            if not self.folder.get():
                self.folder.set(model.folder_offered(look, self.setup))
        self._render()

    def act(self, row, action):
        key = row.key
        board = next((d for d in self.boards if d.key == action.target), None)
        if action.kind == 'page':
            return self.go(next(i for i, (k, _) in enumerate(model.PAGES) if k == action.target))
        if action.kind == 'open':
            return dash.open_page(board)
        if action.kind == 'make':
            job, label = (lambda: model.outcome(action.finding.make())), 'Changing…'
        elif action.kind == 'register':
            job, label = (lambda: viewer.register(*self.context.viewer_keys)), 'Registering…'
        elif action.kind == 'unregister':
            job, label = (lambda: viewer.unregister(*self.context.viewer_keys[:1])), 'Unregistering…'
        else:
            def job():
                ok, text = dash.start(board, self.clone)
                return not ok, text
            label = f'Starting the {board.title.lower()}…'

        def done(result):
            self.details[key] = (True, f'Failed: {result}') if isinstance(result, Exception) else result
            self.reload()
        self.work(label, job, done)

    # --- moving between pages ---

    def go(self, page):
        self.page = page
        self._render()
        self.canvas.yview_moveto(0)

    def finish(self):
        try:
            self.context.first_run.finish(self.clone)
        except OSError as e:
            self.details['read'] = (True, f'The end of the first run could not be kept, in {self.context.first_run.path}: {e}')
        self.go(None)

    def _folder_typed(self):
        if self.typing:
            self.after_cancel(self.typing)
        self.typing = self.after(TYPING_MS, self._render)

    def _browse(self):
        chosen = filedialog.askdirectory(parent=self, initialdir=self.folder.get() or None, title='Folder of the project repos')
        if chosen:
            self.folder.set(chosen.replace('/', '\\'))

    # --- drawing ---

    def _styles(self):
        base = tkfont.nametofont('TkDefaultFont')
        base.configure(family='Segoe UI', size=9)
        tkfont.nametofont('TkTextFont').configure(family='Segoe UI', size=9)
        self.bold = base.copy()
        self.bold.configure(weight='bold')
        self.big = tkfont.Font(self, family='Segoe UI', size=14, weight='bold')
        self.mark_font = tkfont.Font(self, family='Segoe UI Symbol', size=11)
        self.configure(background=BACKGROUND)
        style = ttk.Style(self)
        for name in ('TFrame', 'TLabel'):
            style.configure(name, background=BACKGROUND)
        style.configure('Card.TFrame', background=CARD)
        style.configure('Card.TLabel', background=CARD)
        style.configure('Title.TLabel', background=CARD, font=self.bold)
        style.configure('Gray.TLabel', foreground=GRAY)
        style.configure('Big.TLabel', font=self.big)

    def _layout(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky='ew', padx=16, pady=(14, 0))
        top.columnconfigure(0, weight=1)
        self.heading = ttk.Label(top, style='Big.TLabel')
        self.heading.grid(row=0, column=0, sticky='w')
        self.where = ttk.Label(top, style='Gray.TLabel')
        self.where.grid(row=0, column=1, sticky='e')
        self.intro = ttk.Label(self, wraplength=self.px(WIDTH - 40), justify='left')
        self.intro.grid(row=1, column=0, sticky='ew', padx=16, pady=(6, 8))
        middle = ttk.Frame(self)
        middle.grid(row=2, column=0, sticky='nsew', padx=(16, 4))
        middle.rowconfigure(0, weight=1)
        middle.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(middle, background=BACKGROUND, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(middle, orient='vertical', command=self.canvas.yview)
        bar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=bar.set)
        self.body = ttk.Frame(self.canvas)
        self.body_id = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.body_id, width=e.width))
        self.bind_all('<MouseWheel>', lambda e: self.canvas.yview_scroll(-e.delta // 120, 'units'))
        ttk.Separator(self).grid(row=3, column=0, sticky='ew')
        self.bottom = ttk.Frame(self)
        self.bottom.grid(row=4, column=0, sticky='ew', padx=16, pady=10)

    def _render(self):
        for w in self.body.winfo_children() + self.bottom.winfo_children():
            w.destroy()
        look = self.look
        if look and look.worktree_of:
            return self._render_worktree(look)
        if self.page is None:
            self.heading.configure(text='TIA-co-op settings')
            self.where.configure(text=self.clone)
            self.intro.configure(text=self._settings_intro(look))
            if look:
                for heading, rows in model.settings_groups(look):
                    ttk.Label(self.body, text=heading, style='Big.TLabel', font=self.bold).pack(anchor='w', pady=(10, 2))
                    for row in rows:
                        self._row(row)
        else:
            key, title = model.PAGES[self.page]
            self.heading.configure(text=title)
            self.where.configure(text=f'First setup, page {self.page + 1} of {len(model.PAGES)}')
            self.intro.configure(text=model.INTROS[key])
            if look:
                shown = self._page_look() if key == 'bridge' else look
                if key == 'bridge':
                    self._folder_field(shown)
                for row in model.page_rows(shown, key):
                    self._row(row)
                note = model.page_note(look, key)
                if note:
                    ttk.Label(self.body, text=note, wraplength=self.px(TEXT_WIDTH + 160), justify='left', style='Gray.TLabel').pack(anchor='w', pady=(8, 0))
        self._message()
        self._buttons()

    def _settings_intro(self, look):
        if not look:
            return 'Reading what is set up…'
        count = model.open_items(look)
        state = 'Everything is set up.' if not count else f'{count} not done or missing: each says what it needs.'
        return f'What is registered and where, read just now. {state} Every page of the first setup opens again below.'

    def _page_look(self):
        """The look with the projects step planned for the folder in the field: on the bridge page only."""
        look = dataclasses.replace(self.look, findings=dict(self.look.findings))
        return model.with_folder(look, self.setup, self.folder.get())

    def _folder_field(self, look):
        """The folder of the project repos: the stored one or setup's default, typed or picked. The row under it plans
        for what it holds; the warning on a long path shows here until the row has its own."""
        frame = ttk.Frame(self.body)
        frame.pack(fill='x', pady=(0, 6))
        ttk.Label(frame, text='Project repos folder:').pack(side='left')
        entry = ttk.Entry(frame, textvariable=self.folder, width=60)
        entry.pack(side='left', padx=6)
        ttk.Button(frame, text='Browse…', command=self._browse).pack(side='left')
        warning = model.folder_warning(self.setup, self.folder.get())
        if warning and not any(f.kind == 'warning' for f in look.findings.get('projectsRoot', [])):
            ttk.Label(self.body, text='Warning: ' + warning, foreground=MARKS['warning'][1], wraplength=self.px(TEXT_WIDTH + 160),
                      justify='left').pack(anchor='w')

    def _row(self, row):
        card = ttk.Frame(self.body, style='Card.TFrame', padding=(self.px(10), self.px(8)))
        card.pack(fill='x', pady=3)
        card.columnconfigure(1, weight=1)
        mark, colour = MARKS.get(row.state, MARKS['info'])
        tk.Label(card, text=mark, foreground=colour, background=CARD, font=self.mark_font, width=2).grid(row=0, column=0, rowspan=3, sticky='n')
        ttk.Label(card, text=row.title, style='Title.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Label(card, text=row.text, style='Card.TLabel', wraplength=self.px(TEXT_WIDTH), justify='left').grid(row=1, column=1, sticky='w')
        failed, detail = self.details.get(row.key, (False, ''))
        if failed:      # a change that worked shows in the row read after it; one that failed, here in the tool's words
            ttk.Label(card, text=detail, style='Card.TLabel', foreground=BAD,
                      wraplength=self.px(TEXT_WIDTH), justify='left').grid(row=2, column=1, sticky='w', pady=(4, 0))
        buttons = ttk.Frame(card, style='Card.TFrame')
        buttons.grid(row=0, column=2, rowspan=3, sticky='ne', padx=(8, 0))
        current = model.PAGES[self.page][0] if self.page is not None else None
        for action in row.actions:
            if action.kind == 'page' and action.target == current:
                continue
            ttk.Button(buttons, text=action.label, command=lambda a=action: self.act(row, a),
                       state='disabled' if self.busy else 'normal').pack(side='left', padx=(4, 0))

    def _message(self):
        failed, text = self.details.get('read', (False, ''))
        if text:
            ttk.Label(self.body, text=text, foreground=BAD, wraplength=self.px(TEXT_WIDTH + 160), justify='left').pack(anchor='w', pady=6)

    def _buttons(self):
        state = 'disabled' if self.busy else 'normal'
        ttk.Button(self.bottom, text='Refresh', command=lambda: self.reload(clear=True), state=state).pack(side='left')
        ttk.Label(self.bottom, text=self.busy, style='Gray.TLabel').pack(side='left', padx=10)
        if self.page is None:
            ttk.Button(self.bottom, text='Close', command=self.destroy).pack(side='right')
            for i, (_, title) in reversed(list(enumerate(model.PAGES))):
                ttk.Button(self.bottom, text=f'{i + 1} {title}', command=lambda i=i: self.go(i), state=state).pack(side='right', padx=(4, 0))
            ttk.Label(self.bottom, text='Pages:', style='Gray.TLabel').pack(side='right', padx=4)
            return
        last = self.page == len(model.PAGES) - 1
        ttk.Button(self.bottom, text='Finish' if last else 'Next', state=state,
                   command=self.finish if last else lambda: self.go(self.page + 1)).pack(side='right')
        ttk.Button(self.bottom, text='Back', command=lambda: self.go(self.page - 1),
                   state='disabled' if self.page == 0 or self.busy else 'normal').pack(side='right', padx=4)
        if self.context.first_run.done(self.clone):
            ttk.Button(self.bottom, text='Settings', command=lambda: self.go(None), state=state).pack(side='right', padx=12)

    def _render_worktree(self, look):
        self.heading.configure(text='A worktree')
        self.where.configure(text=self.clone)
        self.intro.configure(text=model.sentence(self.setup.worktree_refusal(look.worktree_of)) + ' Double-click Setup in the main tree for its settings.')
        ttk.Button(self.bottom, text='Close', command=self.destroy).pack(side='right')
