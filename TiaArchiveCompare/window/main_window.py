"""The window: two pickers, options, Compare; the step list, progress and live log of the runner; the result.
It never talks to TIA: everything it shows comes from the runner's events (RunModel)."""
import os
import queue
import subprocess
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import filedialog, font as tkfont, messagebox, ttk

from TiaArchiveCompare.runner import checks, gitrepo
from TiaArchiveCompare.window import ask_dialog
from TiaArchiveCompare.window.ask_dialog import AskAnswer
from TiaArchiveCompare.window.clipboard import copy_text
from TiaArchiveCompare.window.edit_menu import add_edit_menu
from TiaArchiveCompare.window.file_drop import accept_drops
from TiaArchiveCompare.window.model import (TITLE, CommitChoice, RunModel, RunOptions, StepState, answer_command,
                                            cancel_command, clean_path, clock, default_title, runner_arguments, skip_command)
from TiaArchiveCompare.window.runner_process import RunnerProcess
from TiaArchiveCompare.window.settings import Settings, folder_of

ACCENT, ACCENT_OFF = '#4a5058', '#b4b7bb'
OK, BAD, GRAY = '#007800', '#b22222', '#808080'
BACKGROUND = '#f6f7f9'
BOX_OFF = '#f0f0f0'         # what the theme paints in a box that is locked; read from a shot of the window
WIDTH, HEIGHT = 1100, 780
PUMP_MS, CLOCK_MS, TIP_MS = 30, 500, 500
STATE_MARK = {StepState.RUNNING: '▶', StepState.DONE: '✔', StepState.FAILED: '✖',
              StepState.CANCELLED: '■', StepState.SKIPPED: '–', StepState.PENDING: '○'}
ARCHIVE_TYPES = [('TIA archives and projects', '*.zap20 *.zap19 *.ap20 *.ap19'), ('All files', '*.*')]
CHOOSE_ARCHIVES = 'Choose two archives, project folders or export folders and press Compare.'
CHOOSE_COMMITS = 'Choose a git repo and two of its commits and press Compare.'
COMMIT_LIST_ROWS = 20


class RowTips:
    """The whole text of a row, as a small window under the pointer."""

    def __init__(self, tree, text_of):
        self.tree, self.text_of = tree, text_of
        self.row, self.tip, self.pending = None, None, None
        tree.bind('<Motion>', self._moved)
        tree.bind('<Leave>', lambda e: self._set_row(None))

    def _moved(self, event):
        self._set_row(self.tree.identify_row(event.y) or None)

    def _set_row(self, row):
        if row == self.row:
            return
        self.row = row
        if self.pending:
            self.tree.after_cancel(self.pending)
            self.pending = None
        if self.tip:
            self.tip.destroy()
            self.tip = None
        if row:
            self.pending = self.tree.after(TIP_MS, self._show)

    def _show(self):
        self.pending = None
        text = self.text_of(self.row) if self.row and self.tree.exists(self.row) else None
        if not text:
            return
        self.tip = tk.Toplevel(self.tree)
        self.tip.overrideredirect(True)
        self.tip.geometry('+%d+%d' % (self.tree.winfo_pointerx() + 12, self.tree.winfo_pointery() + 16))
        tk.Label(self.tip, text=text, background='#ffffe1', relief='solid', borderwidth=1, justify='left',
                 wraplength=600, padx=4, pady=2).pack()


class MainWindow(tk.Tk):
    def __init__(self, runner_command, settings_path):
        super().__init__()
        self.runner_command = runner_command
        self.settings_path = settings_path
        self.settings = Settings.load(settings_path)
        self.model = RunModel()
        self.runner = None
        self.events = queue.Queue()
        self.drops = queue.Queue()
        self.log_shown = 0
        self.stop_offered = False
        self.close_when_ended = False
        self.clock_job = None
        self.rows = {}              # what a step row shows now: a tick redraws only what changed
        self.ask_handler = lambda request: ask_dialog.ask(self, request)   # the headless check replaces it
        self.on_run_ended = None
        self.headless = False

        self.before_path = tk.StringVar(self)
        self.after_path = tk.StringVar(self)
        self.title_text = tk.StringVar(self)
        self.compile = tk.BooleanVar(self, False)
        self.safety = tk.BooleanVar(self, False)
        self.hmi = tk.BooleanVar(self, False)
        self.no_cache = tk.BooleanVar(self, False)
        self.details = tk.BooleanVar(self, False)
        self.from_commits = tk.BooleanVar(self, False)
        self.repo_path = tk.StringVar(self)
        self.before_commit = tk.StringVar(self)
        self.after_commit = tk.StringVar(self)
        self.choice = CommitChoice()
        self.inputs = []
        self.scale = self.winfo_fpixels('1i') / 96

        self.title(TITLE)
        self._styles()
        self._layout()
        self.compile.trace_add('write', lambda *_: self._compile_changed())
        self.details.trace_add('write', lambda *_: self._details_changed())
        self.from_commits.trace_add('write', lambda *_: self._mode_changed())
        for variable in (self.before_path, self.after_path, self.title_text):
            variable.trace_add('write', lambda *_: self._update_title_cue())
        self._update_title_cue()
        self.bind('<Return>', self._enter)
        self.protocol('WM_DELETE_WINDOW', self._closing)
        self.minsize(self.px(1000), self.px(700))
        self._center(self.px(WIDTH), self.px(HEIGHT))
        self.after(PUMP_MS, self._pump)

    def px(self, pixels):
        """A size given for a screen at 100%, on this one."""
        return int(pixels * self.scale)

    @staticmethod
    def _enter(event):
        """Enter presses the button in focus, as in a Windows window; Tk's buttons take only the space bar."""
        if isinstance(event.widget, (tk.Button, ttk.Button)):
            event.widget.invoke()

    def _center(self, width, height):
        self.geometry('%dx%d+%d+%d' % (width, height, max(0, (self.winfo_screenwidth() - width) // 2),
                                       max(0, (self.winfo_screenheight() - height) // 2)))

    def _styles(self):
        base = tkfont.nametofont('TkDefaultFont')
        base.configure(family='Segoe UI', size=9)
        tkfont.nametofont('TkTextFont').configure(family='Segoe UI', size=9)
        self.bold = base.copy()
        self.bold.configure(weight='bold')
        self.result_font = tkfont.Font(self, family='Segoe UI', size=10, weight='bold')
        self.go_font = tkfont.Font(self, family='Segoe UI', size=11, weight='bold')
        self.log_font = tkfont.Font(self, family='Consolas', size=-self.px(11))     # 8.5 points: Tk takes whole points only
        self.configure(background=BACKGROUND)
        style = ttk.Style(self)
        for name in ('TFrame', 'TLabel', 'TCheckbutton', 'TRadiobutton'):
            style.configure(name, background=BACKGROUND)
        style.configure('Heading.TLabel', font=self.bold)
        style.configure('Cue.TLabel', background='white', foreground=GRAY, padding=0)
        style.configure('Stop.TButton', foreground=BAD)
        style.configure('Treeview', rowheight=base.metrics('linespace') + self.px(4), background='white')

    # --- layout ---

    def _layout(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._top().grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 0))
        self._middle().grid(row=1, column=0, sticky='nsew', padx=12, pady=(8, 0))
        self._bottom().grid(row=2, column=0, sticky='ew', padx=12, pady=(8, 12))

    def _top(self):
        top = ttk.Frame(self)
        top.columnconfigure(1, weight=1)
        self.archive_rows, self.commit_rows = [], []    # the rows of the one mode and of the other, in the same cells
        self._mode_row(top, 0)
        self._repo_row(top, 1)
        self.before_box = self._picker(top, 'Before', self.before_path, 2, True)
        self.after_box = self._picker(top, 'After', self.after_path, 3, False)
        self.before_commit_box = self._commit_picker(top, 'Before', self.before_commit, 2, True)
        self.after_commit_box = self._commit_picker(top, 'After', self.after_commit, 3, False)
        ttk.Label(top, text='Title').grid(row=4, column=0, sticky='w', padx=(0, 8), pady=3)
        self.title_box = ttk.Entry(top, textvariable=self.title_text)
        self.title_box.grid(row=4, column=1, columnspan=3, sticky='ew', pady=3)
        add_edit_menu(self.title_box)
        self.inputs.append(self.title_box)
        # Tk's entry has no placeholder of its own: a label that stands on the box while it is empty
        self.title_cue = ttk.Label(top, style='Cue.TLabel', cursor='xterm')
        self.title_cue.bind('<Button-1>', lambda e: self.title_box.focus_set())
        self.title_cue.bind('<Button-3>', lambda e: self.title_box.event_generate('<Button-3>', rootx=e.x_root, rooty=e.y_root))

        self.compare_button = tk.Button(top, text='Compare', font=self.go_font, background=ACCENT, foreground='white', relief='flat',
                            activebackground=ACCENT, activeforeground='white', disabledforeground='white',
                            width=12, command=self.start_run)
        self.compare_button.grid(row=0, column=4, rowspan=5, sticky='nsew', padx=(12, 0), pady=3)

        options = ttk.Frame(top)
        options.grid(row=5, column=1, columnspan=4, sticky='w', pady=(6, 0))
        self.archive_rows.append(options)
        self.options = {}
        self._check(options, self.compile, 'Compile (Uncompiled blocks will not export, not needed if project is already compiled)', 0, 0, 0)
        self.safety_box = self._check(options, self.safety, 'Include safety (asks for the safety password)', 1, 0, 18)
        self._check(options, self.hmi, 'Compare HMIs (slow)', 0, 1, 24)
        self._check(options, self.no_cache, 'Export again (ignore exports kept from earlier runs)', 1, 1, 24)
        self.safety_box.state(['disabled'])
        self._show_mode()
        return top

    def _mode_row(self, parent, row):
        ttk.Label(parent, text='Compare').grid(row=row, column=0, sticky='w', padx=(0, 8), pady=3)
        modes = ttk.Frame(parent)
        modes.grid(row=row, column=1, columnspan=3, sticky='w', pady=3)
        for column, (text, value) in enumerate((('Two archives or folders', False), ('Two commits of a git repo', True))):
            button = ttk.Radiobutton(modes, text=text, variable=self.from_commits, value=value)
            button.grid(row=0, column=column, padx=(0, 16))
            self.inputs.append(button)

    def _repo_row(self, parent, row):
        label = ttk.Label(parent, text='Git repo')
        label.grid(row=row, column=0, sticky='w', padx=(0, 8), pady=3)
        self.repo_box = ttk.Combobox(parent, textvariable=self.repo_path, state='readonly', height=COMMIT_LIST_ROWS)
        self.repo_box.grid(row=row, column=1, columnspan=2, sticky='ew', pady=3)
        self.repo_box.bind('<<ComboboxSelected>>', lambda e: self._repo_picked(self.repo_path.get()))
        folder = ttk.Button(parent, text='Folder...', command=self._pick_repo_folder)
        folder.grid(row=row, column=3, padx=(6, 0), pady=3)
        self.inputs += [self.repo_box, folder]
        self.commit_rows += [label, self.repo_box, folder]

    def _commit_picker(self, parent, label, variable, row, is_before):
        text = ttk.Label(parent, text=label)
        text.grid(row=row, column=0, sticky='w', padx=(0, 8), pady=3)
        box = ttk.Combobox(parent, textvariable=variable, state='readonly', height=COMMIT_LIST_ROWS)
        box.grid(row=row, column=1, columnspan=3, sticky='ew', pady=3)
        box.bind('<<ComboboxSelected>>', lambda e: self._commit_picked(box, is_before))
        self.inputs.append(box)
        self.commit_rows += [text, box]
        return box

    def _picker(self, parent, label, variable, row, is_before):
        text = ttk.Label(parent, text=label)
        text.grid(row=row, column=0, sticky='w', padx=(0, 8), pady=3)
        box = ttk.Entry(parent, textvariable=variable)
        box.grid(row=row, column=1, sticky='ew', pady=3)
        add_edit_menu(box)
        accept_drops(box, lambda path: self.drops.put((variable, path)))
        archive = ttk.Button(parent, text='Archive...', command=lambda: self._pick_file(variable, is_before))
        archive.grid(row=row, column=2, padx=(8, 0), pady=3)
        folder = ttk.Button(parent, text='Folder...', command=lambda: self._pick_folder(variable, is_before))
        folder.grid(row=row, column=3, padx=(6, 0), pady=3)
        self.inputs += [box, archive, folder]
        self.archive_rows += [text, box, archive, folder]
        return box

    def _check(self, parent, variable, text, row, column, indent):
        box = ttk.Checkbutton(parent, text=text, variable=variable)
        box.grid(row=row, column=column, sticky='w', padx=(self.px(indent), 0), pady=1)
        self.inputs.append(box)
        self.options[text] = box
        return box

    def _middle(self):
        middle = ttk.Frame(self)
        middle.rowconfigure(0, weight=1)
        middle.columnconfigure(1, weight=1)

        left = ttk.Frame(middle, width=self.px(520))
        left.grid(row=0, column=0, sticky='ns', padx=(0, 12))
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text='Steps', style='Heading.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 2))
        self.steps = self._tree(left, ('mark', 'text', 'time'), 'tree', 1, 8)
        self.steps.column('#0', width=0, stretch=False)
        self.steps.column('mark', width=self.px(26), stretch=False, anchor='center')
        self.steps.column('text', width=self.px(352), stretch=True)
        self.steps.column('time', width=self.px(118), stretch=False, anchor='e')
        for state, color in ((StepState.DONE, OK), (StepState.FAILED, BAD), (StepState.RUNNING, 'black'),
                             (StepState.PENDING, GRAY), (StepState.CANCELLED, GRAY), (StepState.SKIPPED, GRAY)):
            self.steps.tag_configure(state.value, foreground=color)
        self.steps.tag_configure(StepState.RUNNING.value, font=self.bold)
        self.step_tips = RowTips(self.steps, lambda row: self.steps.set(row, 'text'))

        self.step_error = ttk.Label(left, foreground=BAD, wraplength=self.px(500), justify='left')
        self.step_error.grid(row=2, column=0, sticky='w', pady=(4, 0))
        self.not_exported_label = ttk.Label(left, text='Not in the report', style='Heading.TLabel')
        self.not_exported_label.grid(row=3, column=0, sticky='w', pady=(6, 2))
        self.not_exported = self._tree(left, ('object', 'why'), 'headings', 4, 5)
        self.not_exported.heading('object', text='Object', anchor='w')
        self.not_exported.heading('why', text='Why', anchor='w')
        self.not_exported.column('object', width=self.px(210))
        self.not_exported.column('why', width=self.px(286))
        self.not_exported_tips = RowTips(
            self.not_exported, lambda row: '%s: %s' % tuple(self.not_exported.item(row, 'values')))

        right = ttk.Frame(middle)
        right.grid(row=0, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        ttk.Label(right, text='Log', style='Heading.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 2))
        ttk.Checkbutton(right, text='Show details', variable=self.details).grid(row=0, column=0, columnspan=2, sticky='e')
        self.log = tk.Text(right, wrap='none', font=self.log_font, background='white', state='disabled',
                           width=1, height=1, relief='solid', borderwidth=1)
        self.log.grid(row=1, column=0, sticky='nsew')
        self.log.bind('<Button-1>', lambda e: self.log.focus_set())   # so Ctrl+C copies from a read-only box
        add_edit_menu(self.log, cut=False, paste=False)
        down = ttk.Scrollbar(right, orient='vertical', command=self.log.yview)
        down.grid(row=1, column=1, sticky='ns')
        across = ttk.Scrollbar(right, orient='horizontal', command=self.log.xview)
        across.grid(row=2, column=0, sticky='ew')
        self.log.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        return middle

    def _tree(self, parent, columns, show, row, height):
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=0, sticky='nsew')
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        tree = ttk.Treeview(holder, columns=columns, show=show, height=height, selectmode='browse')
        tree.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(holder, orient='vertical', command=tree.yview)
        bar.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=bar.set)
        return tree

    def _bottom(self):
        bottom = ttk.Frame(self)
        bottom.columnconfigure(0, weight=1)
        self.current = ttk.Label(bottom, width=1)
        self.current.grid(row=0, column=0, sticky='ew')
        self.bar = ttk.Progressbar(bottom, mode='determinate')
        self.bar.grid(row=1, column=0, sticky='ew', pady=(2, 0))
        self.cancel = ttk.Button(bottom, text='Cancel', command=self.press_cancel)
        self.cancel.grid(row=0, column=1, rowspan=2, sticky='nsew', padx=(12, 0), ipadx=self.px(16))
        self.cancel.state(['disabled'])
        self.result = ttk.Label(bottom, font=self.result_font, justify='left',
                                text=CHOOSE_ARCHIVES)
        self.result.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(8, 6))
        # the whole message, on as many lines as it takes: the steps and the log give way
        bottom.bind('<Configure>', lambda e: self.result.configure(wraplength=e.width))
        buttons = ttk.Frame(bottom)
        buttons.grid(row=3, column=0, columnspan=2, sticky='w')
        self.open_report_button = ttk.Button(buttons, text='Open report', command=self.open_report, width=14)
        self.open_folder_button = ttk.Button(buttons, text='Open folder', command=self.open_folder, width=14)
        self.copy_log_button = ttk.Button(buttons, text='Copy log', command=self.copy_log, width=14)
        for button in (self.open_report_button, self.open_folder_button, self.copy_log_button):
            button.pack(side='left', padx=(0, 8))
            button.state(['disabled'])
        return bottom

    # --- pickers ---

    def _last_folder(self, is_before):
        s = self.settings
        folder = (s.before_folder or s.after_folder) if is_before else (s.after_folder or s.before_folder)
        return folder if folder and os.path.isdir(folder) else None

    def _remember(self, is_before, folder):
        if folder is None:
            return
        if is_before:
            self.settings.before_folder = folder
        else:
            self.settings.after_folder = folder
        self.settings.save(self.settings_path)

    def _pick_file(self, variable, is_before):
        path = filedialog.askopenfilename(parent=self, filetypes=ARCHIVE_TYPES, initialdir=self._last_folder(is_before),
                                          title='%s: archive or project' % ('Before' if is_before else 'After'))
        if path:
            path = os.path.normpath(path)
            variable.set(path)
            self._remember(is_before, folder_of(path, False))

    def _pick_folder(self, variable, is_before):
        path = filedialog.askdirectory(parent=self, mustexist=True, initialdir=self._last_folder(is_before),
                                       title='%s: a project folder or an export folder of an earlier run.' % (
                                           'Before' if is_before else 'After'))
        if path:
            path = os.path.normpath(path)
            variable.set(path)
            self._remember(is_before, folder_of(path, True))

    # --- the two commits ---

    def _show_mode(self):
        commits = self.from_commits.get()
        for widget in self.archive_rows:
            widget.grid_remove() if commits else widget.grid()
        for widget in self.commit_rows:
            widget.grid() if commits else widget.grid_remove()

    def _mode_changed(self):
        self._show_mode()
        commits = self.from_commits.get()
        if commits:
            self.repo_box['values'] = gitrepo.project_repos(checks.projects_roots())
        if self.model.end is None and not self.running:
            problem = self.choice.problem if commits else None
            self._show_result(problem or (CHOOSE_COMMITS if commits else CHOOSE_ARCHIVES), BAD if problem else 'black')
        self._update_title_cue()

    def _pick_repo_folder(self):
        roots = [r for r in checks.projects_roots() if os.path.isdir(r)]
        path = filedialog.askdirectory(parent=self, mustexist=True, initialdir=self.choice.repo or (roots[0] if roots else None),
                                       title='The folder of a git repo')
        if path:
            self._repo_picked(os.path.normpath(path))

    def _repo_picked(self, path):
        self.use_repo(path)
        problem = self.choice.problem
        self._show_result(problem or CHOOSE_COMMITS, BAD if problem else 'black')

    def use_repo(self, path, before=None, after=None):
        """Reads the repo's commits into the pickers; before, after: revisions named on the command line."""
        path = os.path.normpath(path)
        commits, problem = gitrepo.read_commits(path)
        self.choice.set_repo(path, commits, problem)
        if before or after:
            self.choice.name_commits(before or '', after or '')
        self.repo_path.set(path)
        if path not in self.repo_box['values']:
            self.repo_box['values'] = tuple(self.repo_box['values']) + (path,)
        for box in (self.before_commit_box, self.after_commit_box):
            box['values'] = self.choice.labels
        self._show_commits()

    def _commit_picked(self, box, is_before):
        self.choice.pick(is_before, box.current())
        box.selection_clear()
        self._show_commits()

    def _show_commits(self):
        self.before_commit.set(self.choice.label_of(self.choice.before))
        self.after_commit.set(self.choice.label_of(self.choice.after))
        self._update_title_cue()

    def _update_title_cue(self):
        if self.title_text.get():
            self.title_cue.place_forget()
            return
        ttk.Style(self).configure('Cue.TLabel', background=BOX_OFF if self.running else 'white')
        if self.from_commits.get():
            both = self.choice.repo and self.choice.before and self.choice.after
            text = self.choice.default_title() if both else 'Default: the repo and the two commits'
        else:
            both = clean_path(self.before_path.get()) and clean_path(self.after_path.get())
            text = default_title(self.before_path.get(), self.after_path.get()) if both else 'Default: the two archive names'
        self.title_cue.configure(text=text)
        # inside the box's border: a label over it would cut the line, and a long title stops at the box's end
        self.title_cue.place(in_=self.title_box, x=self.px(4), y=self.px(1), relheight=1.0, height=-self.px(3),
                             relwidth=1.0, width=-self.px(8))

    def _compile_changed(self):
        if self.compile.get() and not self.running:
            self.safety_box.state(['!disabled'])
        else:
            self.safety_box.state(['disabled'])
        if not self.compile.get():
            self.safety.set(False)

    # --- run ---

    @property
    def running(self):
        return self.runner is not None and self.model.end is None

    def start_run(self):
        if self.running:
            return
        options = self._commit_options() if self.from_commits.get() else self._archive_options()
        if options is None:
            return

        self.model.start(datetime.now(), options.from_commits)
        self.log_shown = 0
        self._clear_log()
        self.steps.delete(*self.steps.get_children())
        self.rows = {}
        self.not_exported.delete(*self.not_exported.get_children())
        self.step_error.configure(text='')
        self.stop_offered = False
        self.cancel.configure(text='Cancel', style='TButton')
        self.not_exported_label.configure(text='Not in the report')
        self.open_report_button.state(['disabled'])
        self.open_folder_button.state(['disabled'])
        self.copy_log_button.state(['!disabled'])
        self._show_result('Running...', 'black')

        # Lines of a runner stopped earlier may still be on their way: each goes with the runner it came from.
        runner = RunnerProcess(lambda line: self.events.put((runner, 'line', line)),
                               lambda line: self.events.put((runner, 'stderr', line)),
                               lambda code: self.events.put((runner, 'exited', code)))
        try:
            runner.start(self.runner_command.exe, runner_arguments(self.runner_command.prefix, options),
                         self.runner_command.work_dir)
        except (OSError, ValueError) as e:
            self.runner = None
            self._show_result(self.runner_command.start_failure(getattr(e, 'strerror', None) or str(e)), BAD)
            return
        self.runner = runner
        self._set_inputs(False)
        self.cancel.state(['!disabled'])
        self.clock_job = self.after(CLOCK_MS, self._tick)
        self._render()

    def _archive_options(self):
        options = RunOptions(before=self.before_path.get(), after=self.after_path.get(), compile=self.compile.get(),
                             safety=self.compile.get() and self.safety.get(), hmi=self.hmi.get(),
                             no_cache=self.no_cache.get())
        invalid = options.validate()
        if invalid is not None:
            self._show_result(invalid, BAD)
            return None
        options.title = self._title_or(default_title(options.before, options.after))
        self._remember(True, folder_of(options.before, os.path.isdir(clean_path(options.before))))
        self._remember(False, folder_of(options.after, os.path.isdir(clean_path(options.after))))
        return options

    def _commit_options(self):
        """A folder that is no repo, a repo with no exports, a commit that is not there: said here, nothing started."""
        c = self.choice
        options = c.options()
        invalid = c.problem or options.validate() or gitrepo.compare_problem(c.repo, c.before, c.after)
        if invalid:
            self._show_result(invalid, BAD)
            return None
        options.title = self._title_or(c.default_title())
        return options

    def _title_or(self, default):
        return self.title_text.get() if self.title_text.get().strip() else default

    def _pump(self):
        """The runner's lines, on the window's thread. The next pump is set first: a question opens its dialog inside
        this call, and the lines keep coming in behind it."""
        self.after(PUMP_MS, self._pump)
        self._take_drops()
        handled = False
        while True:
            try:
                runner, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if runner is not self.runner:
                continue
            handled = True
            if kind == 'line':
                self._on_line(value)
            elif kind == 'stderr':
                self.model.stderr(value, datetime.now())
            elif self.model.end is None:
                self.model.runner_exited(value, datetime.now())
                self._finish()
        if handled:
            self._render()

    def _take_drops(self):
        while True:
            try:
                variable, path = self.drops.get_nowait()
            except queue.Empty:
                return
            if not self.running:    # the boxes are locked during a run
                variable.set(path)

    def _on_line(self, line):
        result = self.model.apply(line, datetime.now())
        if result.ask is not None:
            self._render()
            self._answer(result.ask)
        if result.ended:
            self._finish()

    def _answer(self, request):
        answer = self.ask_handler(request) or AskAnswer(skip=True)
        self.model.asked(request.kind, request.project, answer.skip, datetime.now())
        self.runner.send(skip_command(request.id) if answer.skip
                         else answer_command(request.id, answer.user, answer.password, answer.umc_global))
        answer.password = None
        self._render()

    def press_cancel(self):
        if not self.running:
            return
        if self.stop_offered:
            self._stop_now()
            return
        self.model.cancel_requested(datetime.now())
        self.runner.send(cancel_command())
        self.cancel.state(['disabled'])
        self.cancel.configure(text='Cancelling...')
        self._show_result('Cancelling...' if self.model.from_commits
                          else 'Cancelling: the current TIA call finishes, then TIA is closed and the copy deleted.', 'black')

    def _stop_now(self):
        pid = self.model.tia_pid
        self.runner.kill(pid)
        self.model.add_log(datetime.now(), 'warn',
                           'Stop now: ended the runner%s.' % (' and TIA (process %d)' % pid if pid > 0 else ''))
        self.model.stopped(datetime.now())
        self._finish()

    def _finish(self):
        self._render()
        if self.clock_job:
            self.after_cancel(self.clock_job)
            self.clock_job = None
        self.cancel.state(['disabled'])
        self.cancel.configure(text='Cancel', style='TButton')
        self.bar.stop()
        self.bar.configure(mode='determinate', value=0)
        self.current.configure(text='')
        self._set_inputs(True)
        end = self.model.end
        self._show_result(self.model.result_line(), OK if end.ok else 'black' if end.cancelled else BAD)
        self._enable(self.open_report_button, end.ok and end.report and os.path.isfile(end.report))
        self._enable(self.open_folder_button, end.folder and os.path.isdir(end.folder))
        self.not_exported.delete(*self.not_exported.get_children())
        for item in end.not_exported:
            self.not_exported.insert('', 'end', values=(item.name, item.why))
        self.not_exported_label.configure(text=self.model.not_exported_heading())
        if self.on_run_ended:
            self.on_run_ended()
        if self.close_when_ended:
            self.after_idle(self.destroy)

    @staticmethod
    def _enable(widget, enabled):
        widget.state(['!disabled' if enabled else 'disabled'])

    def _set_inputs(self, enabled):
        for widget in self.inputs:
            self._enable(widget, enabled)
        self._enable(self.safety_box, enabled and self.compile.get())
        self.compare_button.configure(state='normal' if enabled else 'disabled', background=ACCENT if enabled else ACCENT_OFF)
        self._update_title_cue()

    def _tick(self):
        self.clock_job = self.after(CLOCK_MS, self._tick)
        if self.running and not self.stop_offered and self.model.offer_stop_now(datetime.now()):
            self.stop_offered = True
            self.cancel.configure(text='Stop now', style='Stop.TButton')
            self.cancel.state(['!disabled'])
            self._show_result(self.model.stop_now_offer(), BAD)
        self._render()

    def _show_result(self, text, color):
        self.result.configure(text=text, foreground=color)

    def _render(self):
        """Model -> controls. Cheap enough to run after every batch of events and every clock tick."""
        now = datetime.now()
        if len(self.rows) != len(self.model.steps):
            self.steps.delete(*self.steps.get_children())
            self.rows = {}
        for index, s in enumerate(self.model.steps):
            row = str(index)
            shown = ((STATE_MARK[s.state], s.text, self.model.step_time(s, now)), s.state.value)
            if self.rows.get(row) == shown:
                continue
            if row in self.rows:
                self.steps.item(row, values=shown[0], tags=(shown[1],))
            else:
                self.steps.insert('', 'end', iid=row, values=shown[0], tags=(shown[1],))
            self.rows[row] = shown
        step_error, result = self.model.step_error, self.model.result_line()
        # not twice when the result says it
        self.step_error.configure(text='' if step_error is None or (result and step_error in result) else step_error)

        p = self.model.progress
        if p is not None and p.total > 0:
            self.bar.stop()
            self.bar.configure(mode='determinate', maximum=p.total, value=min(p.done, p.total))
        elif self.running and self.model.current_step is not None:
            if str(self.bar['mode']) != 'indeterminate':
                self.bar.configure(mode='indeterminate', maximum=100, value=0)
                self.bar.start(30)
        elif str(self.bar['mode']) == 'indeterminate':
            self.bar.stop()
            self.bar.configure(mode='determinate', value=0)
        if self.running:
            self._show_current('%s    %s elapsed' % (self.model.progress_line(now), clock(now - self.model.started_at)))
        self._refresh_log()

    def _show_current(self, text):
        """Cut at the end when it does not fit: the label must not push Cancel away."""
        room, font = self.current.winfo_width(), tkfont.nametofont('TkDefaultFont')
        if room > 1 and font.measure(text) > room:
            while text and font.measure(text + '...') > room:
                text = text[:-max(1, (font.measure(text) - room) // 8)]
            text += '...'
        self.current.configure(text=text)

    def _details_changed(self):
        self._clear_log()
        self.log_shown = 0
        self._refresh_log()

    def _clear_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    def _refresh_log(self):
        if self.log_shown >= len(self.model.log):
            return
        details = self.details.get()
        text = ''.join('%s\n' % line for line in self.model.log[self.log_shown:] if details or not line.detail)
        self.log_shown = len(self.model.log)
        if text:
            self.log.configure(state='normal')
            self.log.insert('end', text)
            self.log.configure(state='disabled')
            self.log.see('end')

    @property
    def shown_log(self):
        """What the log box shows (the headless check)."""
        return self.log.get('1.0', 'end-1c')

    # --- result buttons ---

    def open_report(self):
        report = self.model.end.report if self.model.end else None
        if not report:
            return
        try:
            os.startfile(report)
        except OSError as e:
            self._show_result('Could not open the report: %s' % (e.strerror or e), BAD)

    def open_folder(self):
        folder = self.model.end.folder if self.model.end else None
        if not folder:
            return
        try:
            subprocess.Popen(['explorer.exe', folder])
        except OSError as e:
            self._show_result('Could not open the folder: %s' % (e.strerror or e), BAD)

    def copy_log(self):
        text = self.model.log_text()
        if text and not copy_text(text):
            self._show_result('Could not copy the log: another program holds the clipboard. Try again.', BAD)

    # --- closing, failures ---

    def _closing(self):
        if not self.running:
            self.destroy()
            return
        if self.close_when_ended or self.headless:   # closes itself when the run has ended
            return
        if messagebox.askyesno('TIA Archive Compare', self.model.close_question(), parent=self):
            self.close_when_ended = True
            self.press_cancel()

    def report_callback_exception(self, exc, value, tb):
        """pythonw has no stderr: a fault of the window shows in the window, and stands in Copy log."""
        self.model.add_log(datetime.now(), 'error', ''.join(traceback.format_exception(exc, value, tb)).rstrip())
        self._show_result('The window failed: %s. See the log.' % value, BAD)
        self.copy_log_button.state(['!disabled'])
        self._refresh_log()
