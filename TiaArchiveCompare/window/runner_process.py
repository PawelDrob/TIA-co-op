"""The runner as a child process: event lines from stdout, diagnostics from stderr, commands to stdin (UTF-8)."""
import os
import signal
import subprocess
import threading

DEFAULT_MODULE = 'TiaArchiveCompare.runner'
NO_WINDOW = subprocess.CREATE_NO_WINDOW


class RunnerProcess:
    """on_line, on_error_line and on_exited are called on reader threads: the window hands them to its own thread."""

    def __init__(self, on_line, on_error_line, on_exited):
        self.on_line, self.on_error_line, self.on_exited = on_line, on_error_line, on_exited
        self.process = None

    def start(self, exe, args, work_dir):
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        self.process = subprocess.Popen([exe] + list(args), cwd=work_dir, env=env, creationflags=NO_WINDOW,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        errors = threading.Thread(target=self._read, args=(self.process.stderr, self.on_error_line), daemon=True)
        errors.start()
        threading.Thread(target=self._read_to_the_end, args=(errors,), daemon=True).start()

    def _read_to_the_end(self, errors):
        self._read(self.process.stdout, self.on_line)
        code = self.process.wait()
        errors.join(5)      # a child that keeps the pipe open must not hold back the end of the run
        self.on_exited(code)

    @staticmethod
    def _read(stream, on_line):
        try:
            for raw in stream:
                on_line(raw.decode('utf-8', 'replace').rstrip('\r\n'))
        except (OSError, ValueError):
            pass

    def send(self, command):
        """One command line to the runner. A runner that is gone says so itself: its end comes as on_exited."""
        try:
            self.process.stdin.write(command.encode('utf-8') + b'\n')
            self.process.stdin.flush()
        except (OSError, ValueError):
            pass

    def kill(self, tia_pid):
        """"Stop now": the runner with its children (the exporter), and the TIA it reported."""
        if self.process is not None:
            _kill_tree(self.process.pid)
        if tia_pid > 0:
            _kill_tree(tia_pid)


def _kill_tree(pid):
    taskkill = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe')
    try:
        subprocess.run([taskkill, '/PID', str(pid), '/T', '/F'], creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


class RunnerCommand:
    """Where the runner is and how it is started. Defaults: <root>\\.venv\\Scripts\\python.exe -X utf8 -m
    TiaArchiveCompare.runner run, from <root>, the folder that holds the package (searched upwards from the window's
    folder); a python\\python.exe in the window's folder comes first (packaging). Never python from PATH."""

    def __init__(self, exe, prefix, work_dir):
        self.exe, self.prefix, self.work_dir = exe, prefix, work_dir

    @staticmethod
    def resolve(exe, prefix, window_dir):
        prefix = prefix if prefix is not None else ['-X', 'utf8', '-m', DEFAULT_MODULE, 'run']
        command = RunnerCommand(exe, prefix, window_dir)
        if '-m' in prefix and prefix.index('-m') + 1 < len(prefix):
            module = prefix[prefix.index('-m') + 1].replace('.', '\\')
            folder = window_dir
            while True:
                if os.path.isfile(os.path.join(folder, module, '__main__.py')):
                    command.work_dir = folder
                    break
                if os.path.dirname(folder) == folder:
                    break
                folder = os.path.dirname(folder)
        if command.exe is None:
            bundled = os.path.join(window_dir, 'python', 'python.exe')
            command.exe = bundled if os.path.isfile(bundled) else command._venv
        return command

    @property
    def _venv(self):
        return os.path.join(self.work_dir, '.venv', 'Scripts', 'python.exe')

    def start_failure(self, why):
        """The result line when the runner could not be started: names the setup step when the .venv is what is
        missing."""
        text = 'Could not start the runner (%s): %s' % (self.exe, why)
        if self.exe == self._venv and not os.path.isfile(self._venv):
            return '%s Run uv sync in %s once.' % (text, self.work_dir)
        return text
