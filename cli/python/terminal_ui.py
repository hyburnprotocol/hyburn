"""Small, dependency-free terminal dashboard. Presentation only: no RPC or signing."""
from collections import deque
from contextlib import contextmanager
import re
import os
import shutil
import sys
import threading
import time
import select
try:
    import termios
    import tty
except ImportError:  # Non-POSIX terminals keep display + Ctrl-C support.
    termios = tty = None

_CURRENT = None


def current():
    return _CURRENT


def clean(text):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(text))
    return ''.join(c for c in text if c.isprintable())


class LogStream:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.buffer = ''

    def write(self, text):
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line.strip():
                self.dashboard.log(line)
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


class Dashboard:
    def __init__(self, enabled=True, title='HYBURN / MINER'):
        self.output, self.errors = sys.stdout, sys.stderr
        size = shutil.get_terminal_size((80, 24))
        self.enabled = enabled and os.environ.get('TERM') != 'dumb' and self.output.isatty() and self.errors.isatty() and size.columns >= 80 and size.lines >= 24
        self.title = title
        self.fields = {}
        self.events = deque(maxlen=400)
        self.page = 0
        self.scroll = 0
        self.input_fd = None
        self.input_mode = None
        self.status = 'Starting'
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.worker = None

    def update(self, **fields):
        with self.lock:
            self.fields.update({k: clean(v) for k, v in fields.items()})

    def log(self, line):
        with self.lock:
            if self.page == 2 and self.scroll:
                self.scroll = min(self.scroll + 1, 399)
            self.events.append(time.strftime('%H:%M:%S ') + clean(line))
            self.status = clean(line)

    @contextmanager
    def activity(self, label):
        with self.lock:
            previous = self.status
            self.status = label
        try:
            yield
        finally:
            with self.lock:
                self.status = previous

    def handle_key(self, key):
        # Navigation only. Keys never sign, send, claim, or change the burn budget.
        with self.lock:
            if key in ('1', '2', '3', '?'):
                self.page = {'1': 0, '2': 1, '3': 2, '?': 3}[key]
                self.scroll = 0
            elif key == '\t':
                self.page = (self.page + 1) % 4
                self.scroll = 0
            elif key in ('k', '\x1b[A'):
                self.scroll = min(self.scroll + 1, max(0, len(self.events) - 1)) if self.page == 2 else max(0, self.scroll - 1)
            elif key in ('j', '\x1b[B'):
                self.scroll = max(0, self.scroll - 1) if self.page == 2 else min(self.scroll + 1, len(self.fields))
            elif key == 'g':
                self.scroll = 0

    @staticmethod
    def box(title, rows, width, height):
        inside = max(1, width - 2)
        head = (' ' + title + ' ')[:inside]
        lines = ['+' + head + '-' * (inside - len(head)) + '+']
        lines += ['|' + clean(row)[:inside].ljust(inside) + '|' for row in rows[:max(0, height - 2)]]
        while len(lines) < height - 1:
            lines.append('|' + ' ' * inside + '|')
        lines.append('+' + '-' * inside + '+')
        return lines

    def frame(self, width, height):
        width = max(1, width - 1)
        if width < 79 or height < 24:
            return '\n'.join(line[:width] for line in [self.title, 'Resize to at least 80 x 24.', 'Mining continues. Ctrl-C stops.'][:max(0, height)])
        with self.lock:
            status = self.status() if callable(self.status) else self.status
            tabs = ['1 Overview', '2 Wallet / costs', '3 Events', '? Help']
            tabs[self.page] = '[' + tabs[self.page] + ']'
            lines = [self.title, '  '.join(tabs)]
            lines += self.box('ACTIVITY', [f"{'|/-'[int(time.monotonic() * 4) % 3]} {clean(status)}"], width, 3)
            space = max(3, height - len(lines) - 1)
            if self.page == 0:
                left_keys = ['Phase', 'Mode', 'Chain', 'Round (last read)', 'Confirmed burns', 'Burns this run', 'Burn / transaction', 'Burn / round', 'Send window']
                right_keys = ['Balance (snapshot)', 'Available incl. gas', 'Session burned', 'Session gas', 'Session spent', 'Burn budget', 'Burn spending']
                def rows(keys):
                    result = []
                    for key in keys:
                        if key in self.fields:
                            result.extend([key, '  ' + self.fields[key]])
                    return result[:max(0, (panel_height - 2) // 2) * 2] or ['Waiting for first snapshot...']
                panel_height = max(5, space - 5)
                split = width // 2
                left = self.box('MINING', rows(left_keys), split, panel_height)
                right = self.box('HYPE / COSTS', rows(right_keys), width - split, panel_height)
                lines += [a + b for a, b in zip(left, right)]
                lines += self.box('RECENT EVENTS (3: full history)', list(self.events)[-3:], width, 5)
            elif self.page == 1:
                rows = [f'{key:<22} {value}' for key, value in self.fields.items()]
                rows += ['Snapshots from last read. No refresh RPC.', 'Public miner budget: burns only, resets each run.', 'Deploy console cap: saved; includes gas.']
                lines += self.box('WALLET / COSTS - j/k scroll, g top', rows[self.scroll:], width, space)
            elif self.page == 2:
                end = len(self.events) - self.scroll
                rows = list(self.events)[max(0, end - space + 2):end]
                lines += self.box('EVENTS - k older, j newer, g latest', rows, width, space)
            else:
                rows = ['1 / 2 / 3 / ? : overview, wallet & costs, events, help',
                        'Tab: next page. j/k or arrows: scroll. g: reset scroll.',
                        'Ctrl-C: stop mining; already sent transactions may confirm.',
                        'Navigation never sends transactions or changes spending.',
                        'Countdowns are local estimates, not chain confirmations.',
                        'Balances and round data update only when the miner reads them.',
                        'Use --plain for persistent line-by-line logs.',
                        'Keep enough native HYPE for claim gas after your final round.']
                lines += self.box('HELP', rows, width, space)
            lines += ['1 Overview  2 Wallet  3 Events  ? Help  Tab Next  Ctrl-C Stop']
            return '\n'.join(line[:width] for line in lines[:height])

    def render(self):
        while not self.done.is_set():
            if self.input_fd is not None and select.select([self.input_fd], [], [], 0)[0]:
                keys = os.read(self.input_fd, 32).decode('utf-8', errors='ignore')
                if keys in ('\x1b[A', '\x1b[B'):
                    self.handle_key(keys)
                else:
                    for key in keys:
                        self.handle_key(key)
            size = shutil.get_terminal_size((80, 24))
            self.output.write('\x1b[H' + self.frame(size.columns, size.lines).replace('\n', '\x1b[K\r\n') + '\x1b[K\x1b[J')
            self.output.flush()
            self.done.wait(0.25)

    def start(self):
        self.done.clear()
        if termios is not None and sys.stdin.isatty():
            self.input_fd = sys.stdin.fileno()
            self.input_mode = termios.tcgetattr(self.input_fd)
            tty.setcbreak(self.input_fd)  # Keep ISIG: Ctrl-C retains its usual meaning.
        self.output.write('\x1b[?1049h\x1b[?25l\x1b[2J')
        self.output.flush()
        sys.stdout = sys.stderr = LogStream(self)
        self.worker = threading.Thread(target=self.render, daemon=True)
        self.worker.start()

    def stop(self):
        self.done.set()
        if self.worker:
            self.worker.join()
        if self.input_fd is not None and self.input_mode is not None:
            termios.tcsetattr(self.input_fd, termios.TCSADRAIN, self.input_mode)
            self.input_fd = self.input_mode = None
        sys.stdout, sys.stderr = self.output, self.errors
        self.output.write('\x1b[?25h\x1b[?1049l')
        self.output.flush()

    @contextmanager
    def suspended(self):
        global _CURRENT
        if not self.enabled:
            yield
            return
        self.stop()
        _CURRENT = None
        try:
            yield
        finally:
            _CURRENT = self
            self.start()

    def __enter__(self):
        global _CURRENT
        if self.enabled:
            _CURRENT = self
            try:
                self.start()
            except BaseException:
                self.stop()
                _CURRENT = None
                raise
        return self

    def __exit__(self, *_):
        global _CURRENT
        if self.enabled:
            self.stop()
            _CURRENT = None
            for line in list(self.events)[-8:]:
                print(line)
