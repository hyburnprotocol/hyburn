"""Small, dependency-free terminal dashboard. Presentation only: no RPC or signing."""
from collections import deque
from contextlib import contextmanager
import re
import os
import shutil
import sys
import threading
import time

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
        self.events = deque(maxlen=100)
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

    def frame(self, width, height):
        width = max(20, width - 1)
        with self.lock:
            status = self.status() if callable(self.status) else self.status
            lines = [self.title, '=' * width,
                     f"{'|/-'[int(time.monotonic() * 4) % 3]} {clean(status)}"]
            lines += [f'{key:<22} {value}' for key, value in self.fields.items()]
            lines += ['RECENT EVENTS', '-' * width]
            room = max(0, height - len(lines) - 1)
            lines += list(self.events)[-room:] if room else []
            lines += ['Ctrl-C: stop safely | snapshots update on reads, not on screen refresh']
            return '\n'.join(line[:width] for line in lines[:height])

    def render(self):
        while not self.done.is_set():
            size = shutil.get_terminal_size((80, 24))
            self.output.write('\x1b[H' + self.frame(size.columns, size.lines).replace('\n', '\x1b[K\r\n') + '\x1b[K\x1b[J')
            self.output.flush()
            self.done.wait(0.25)

    def start(self):
        self.done.clear()
        self.output.write('\x1b[?1049h\x1b[?25l\x1b[2J')
        self.output.flush()
        sys.stdout = sys.stderr = LogStream(self)
        self.worker = threading.Thread(target=self.render, daemon=True)
        self.worker.start()

    def stop(self):
        self.done.set()
        if self.worker:
            self.worker.join()
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
            self.start()
        return self

    def __exit__(self, *_):
        global _CURRENT
        if self.enabled:
            self.stop()
            _CURRENT = None
            for line in list(self.events)[-8:]:
                print(line)
