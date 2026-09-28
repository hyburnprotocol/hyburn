"""Small, dependency-free terminal dashboard. Presentation only: no RPC or signing."""
from collections import deque
from contextlib import contextmanager
import re
import os
import shutil
import sys
import threading
import time
import textwrap
import select
from functools import wraps
from insight_table import InsightTable
try:
    import termios
    import tty
except ImportError:  # Non-POSIX terminals keep display + Ctrl-C support.
    termios = tty = None

_CURRENT = None

# Terminal approximation of the supplied Hyperliquid Blob network mark.
# Braille cells preserve the SVG silhouette without an image-capable terminal.
NETWORK_MARK = (' ⣀⣀⡀    ⣠⣶⣿⣶⣦⡀', '⢸⣿⣿⣿⣷⠶⠶⣾⣿⣿⣿⣿⣿⡇', '⠈⠛⠛⠋    ⠙⠿⢿⠿⠟⠁')


def current():
    return _CURRENT


def clean(text):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(text))
    return ''.join(c for c in text if c.isprintable())


def transaction_activity(fn):
    """Keep optional statistics idle while preparing/submitting a transaction."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        ui = current()
        if ui:
            ui.signing = True
        try:
            return fn(*args, **kwargs)
        finally:
            if ui:
                ui.signing = False
    return wrapped


def choose_start(auto_start=False, label='Start mining'):
    """No signing, recovery or submission before this explicit choice."""
    if auto_start:
        return True
    ui = current()
    if ui and ui.input_fd is not None:
        ui.start_choice = None
        ui.awaiting_start = True
        ui.update(Mode='STANDBY - no transactions sent')
        ui.log(label + '? S: start / Q: exit. Existing transactions may still confirm.')
        try:
            while ui.start_choice is None:
                time.sleep(.1)
            return ui.start_choice
        finally:
            ui.awaiting_start = False
    if not sys.stdin.isatty():
        raise SystemExit('Start choice requires a terminal. Use --yes for intentional unattended execution.')
    context = ui.suspended() if ui else __import__('contextlib').nullcontext()
    with context:
        try:
            return input(label + '? [y/N] ').strip().lower() in ('y', 'yes')
        except EOFError:
            return False


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
        self.fields = {'Engine': 'python'}
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
        self.chain_clock = None
        self.signing = False
        self.awaiting_start = False
        self.start_choice = None
        self.insights = None
        self.snapshots = {}
        self.public_summaries = {}
        self.insight_messages = {}
        self.tables = {}
        self.stats_paused = False
        self.privacy = False
        self.input_buffer = ''
        self.color = self.enabled and 'NO_COLOR' not in os.environ
        try:
            ''.join(NETWORK_MARK).encode(getattr(self.output, 'encoding', None) or 'utf-8')
            self.mark = NETWORK_MARK
        except (UnicodeEncodeError, LookupError):
            self.mark = ('              ', '  HyperEVM    ', '              ')

    def attach_insights(self, **kwargs):
        if not self.enabled or self.insights:
            return
        from mining_insights import Insights
        self.insights = Insights(self, **kwargs)
        self.insights.start()

    def insight_status(self, page, message):
        with self.lock:
            self.insight_messages[page] = clean(message)

    def insight_snapshot(self, page, rows, caption, note='', records=None, public_summary=None):
        with self.lock:
            self.snapshots[page] = (list(rows), clean(caption), clean(note), time.monotonic())
            self.public_summaries[page] = clean(public_summary) if public_summary is not None else ''
            self.insight_messages[page] = 'Snapshot ready; read-only statistics'
            if records is not None:
                table = self.tables.setdefault(page, InsightTable(page))
                table.set_records(records, self.fields.get('Wallet', ''))

    def sync_chain(self, timestamp, genesis, duration):
        """Anchor the display to an existing RPC read; never fetch or send here."""
        if duration <= 0:
            return
        with self.lock:
            next_round = max(0, (int(timestamp) - genesis) // duration + 1)
            target = genesis + next_round * duration
            self.chain_clock = (time.monotonic(), max(0, target - timestamp), next_round)

    def countdown(self):
        if self.chain_clock is None:
            return 'Round clock: waiting for chain sync'
        anchor, remaining, rid = self.chain_clock
        left = remaining - (time.monotonic() - anchor)
        if left <= 0:
            return f'Round {rid}: awaiting chain confirmation'
        seconds = int(left + 0.999)
        minutes, seconds = divmod(seconds, 60)
        return f'Next round {rid} in ~{minutes:02}:{seconds:02} (local estimate)'

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
        # Start keys only release the main-thread gate; navigation stays read-only.
        with self.lock:
            if self.awaiting_start and key.lower() in ('s', 'q'):
                if self.start_choice is None:
                    self.start_choice = key.lower() == 's'
                return
            table = self.tables.get(self.page) if not self.privacy else None
            if table and table.editing is not None:
                table.handle(key)
                return
            if key == 'v':
                self.privacy = not self.privacy
                return
            if key == 'p' and not self.awaiting_start:
                self.stats_paused = not self.stats_paused
                return
            if key == 'r' and self.insights:
                self.insights.refresh(self.page)
                return
            if table and table.handle(key):
                return
            if key in ('1', '2', '3', '4', '5', '6', '7', '?'):
                self.page = {'1': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6, '?': 7}[key]
                self.scroll = 0
            elif key == '\t':
                self.page = (self.page + 1) % 8
                self.scroll = 0
            elif key in ('k', '\x1b[A'):
                self.scroll = min(self.scroll + 1, max(0, len(self.events) - 1)) if self.page == 2 else max(0, self.scroll - 1)
            elif key in ('j', '\x1b[B'):
                self.scroll = max(0, self.scroll - 1) if self.page == 2 else min(self.scroll + 1, max(len(self.fields), len(self.snapshots.get(self.page, ([],))[0])))
            elif key == 'g':
                self.scroll = 0

    def display_field(self, key, value):
        public = {'Mode', 'Chain', 'Engine', 'Block (last read)', 'Round (last read)', 'Token CA', 'Miner'}
        return '[hidden]' if self.privacy and key not in public else value

    def feed_keys(self, text):
        # Escape sequences can be split across terminal reads; never let their
        # numeric suffix accidentally select a tab.
        self.input_buffer += text
        escapes = ('\x1b[A','\x1b[B','\x1b[5~','\x1b[6~','\x1b[H','\x1b[F')
        while self.input_buffer:
            match = next((e for e in escapes if self.input_buffer.startswith(e)), None)
            if match:
                self.handle_key(match)
                self.input_buffer = self.input_buffer[len(match):]
            elif self.input_buffer.startswith('\x1b'):
                if any(e.startswith(self.input_buffer) for e in escapes):
                    return
                if self.input_buffer.startswith('\x1b['):
                    end = re.match(r'\x1b\[[0-9;]*[A-Za-z~]', self.input_buffer)
                    if end:
                        self.input_buffer = self.input_buffer[end.end():]
                        continue
                self.handle_key('\x1b')
                self.input_buffer = self.input_buffer[1:]
            else:
                self.handle_key(self.input_buffer[0])
                self.input_buffer = self.input_buffer[1:]

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
            return '\n'.join(line[:width] for line in [self.title, 'Resize to at least 80 x 24.', 'Standby: S starts, Q exits.' if self.awaiting_start else 'Mining continues. Ctrl-C stops.'][:max(0, height)])
        with self.lock:
            status = self.status() if callable(self.status) else self.status
            if self.privacy:
                status = 'Privacy view enabled; execution settings unchanged.'
            tabs = ['1 Home', '2 Costs', '3 Logs', '4 Round', '5 Mine', '6 Token', '7 Total', '?']
            tabs[self.page] = '[' + tabs[self.page] + ']'
            lines = [self.mark[0] + '  ' + self.title,
                     self.mark[1] + '  ' + self.countdown(),
                     self.mark[2] + f'  Stats: {"PAUSED" if self.stats_paused else "ON DEMAND"} | Privacy: {"ON" if self.privacy else "OFF"} | local clock',
                     '  '.join(tabs)]
            lines += self.box('ACTIVITY', [f"{'|/-'[int(time.monotonic() * 4) % 3]} {clean(status)}"], width, 3)
            space = max(3, height - len(lines) - 1)
            if self.page == 0:
                left_keys = ['Mode', 'Round (last read)', 'Block (last read)', 'Engine', 'Burn / transaction', 'Burn / round', 'Confirmed burns', 'Session burns', 'Phase', 'Chain', 'Send window']
                right_keys = ['Balance (snapshot)', 'Available incl. gas', 'Session burned', 'Session gas', 'Session spent', 'Burn budget', 'Burn spending']
                def rows(keys):
                    result = []
                    for key in keys:
                        if key in self.fields:
                            result.extend([key, '  ' + self.display_field(key, self.fields[key])])
                    return result[:max(0, (panel_height - 2) // 2) * 2] or ['Waiting for first snapshot...']
                panel_height = max(5, space - 5)
                split = width // 2
                left = self.box('MINING', rows(left_keys), split, panel_height)
                right = self.box('HYPE / COSTS', rows(right_keys), width - split, panel_height)
                lines += [a + b for a, b in zip(left, right)]
                lines += self.box('RECENT EVENTS (3: full history)', (['Log details hidden for sharing.'] if self.privacy else list(self.events)[-3:]), width, 5)
            elif self.page == 1:
                rows = [f'{key:<22} {self.display_field(key,value)}' for key, value in self.fields.items()]
                rows += ['Snapshots from last read. No refresh RPC.', 'Public miner budget: saved across restarts; gas extra.', 'Deploy console cap: saved; includes gas.']
                lines += self.box('WALLET / COSTS - j/k scroll, g top', rows[self.scroll:], width, space)
            elif self.page == 2:
                end = len(self.events) - self.scroll
                rows = ['Log details hidden for sharing.'] if self.privacy else list(self.events)[max(0, end - space + 2):end]
                lines += self.box('EVENTS - k older, j newer, g latest', rows, width, space)
            elif self.page in (3, 4, 6):
                snapshot = self.snapshots.get(self.page)
                title = {3:'CURRENT ROUND / BURN RANK',4:'MY RECENT ROUNDS',6:'ALL-TIME / MINING PARTICIPATION'}[self.page]
                rows = ['Statistics PAUSED (p resumes; mining is unchanged)' if self.stats_paused else self.insight_messages.get(self.page, 'Open this tab after starting to load statistics.')]
                if self.privacy:
                    rows = ['Public statistics only; personal rows and filters hidden.']
                if snapshot:
                    data, caption, note, updated = snapshot
                    if self.privacy:
                        if self.page == 4:
                            rows = ['Personal round history hidden for sharing.']
                        else:
                            rows += textwrap.wrap(self.public_summaries.get(self.page) or 'Public summary not available yet.', width=max(1,width-2))
                            rows += [f'Updated {int(time.monotonic()-updated)}s ago (snapshot, not live)',
                                     'Wallets are not people. No personal wallet markers shown.']
                    else:
                        rows += [caption, f'Updated {int(time.monotonic()-updated)}s ago (snapshot, not live)', note]
                    if not self.privacy and self.page in self.tables:
                        rows += self.tables[self.page].render(width-2, space-2-len(rows), self.privacy)
                    elif not self.privacy:
                        rows += data[self.scroll:]
                lines += self.box(title, rows, width, space)
            elif self.page == 5:
                rows = ['Token CA (from the miner contract):', self.fields.get('Token CA', 'Not read yet'),
                        'Miner contract (different from the token):', self.fields.get('Miner', '--'),
                        'Chain: ' + self.fields.get('Chain', '--'),
                        'Verify the address on this chain, not just the name.']
                lines += self.box('TOKEN IDENTITY', rows, width, space)
            else:
                rows = ['1 / 2 / 3 / ? : overview, wallet & costs, events, help',
                        '4: current round. 5: your history. 6: token. 7: all-time.',
                        'Tables: / search, o sort, m your wallet, f claim status.',
                        'c clears filters. j/k select; PgUp/PgDn move five rows.',
                        'r requests refresh (cooldowns apply). p pauses STATISTICS.',
                        'v privacy: public totals only; hides personal rows/logs.',
                        'Privacy does not hide window titles or shell scrollback.',
                        'Tab: next page. j/k or arrows: scroll. g: reset scroll.',
                        'Ctrl-C: stop mining; already sent transactions may confirm.',
                        'Navigation never sends transactions or changes spending.',
                        'Countdowns are local estimates, not chain confirmations.',
                        'Balances and round data update only when the miner reads them.',
                        'Use --plain for persistent line-by-line logs.',
                        'Keep enough native HYPE for claim gas after your final round.']
                lines += self.box('HELP', rows, width, space)
            lines += ['S: START   Q: EXIT   (no new submissions until start)' if self.awaiting_start else 'Tab: next  r: refresh  p: stats pause  v: privacy  ?: help  Ctrl-C: stop']
            return '\n'.join(line[:width] for line in lines[:height])

    def styled_frame(self, width, height):
        """Apply color after layout so ANSI escapes never affect column widths."""
        frame = self.frame(width, height)
        if not self.color:
            return frame
        lines = []
        for index, line in enumerate(frame.splitlines()):
            lower = line.lower()
            code = '0'
            if index < 3:
                code = '1;36'  # Cyan network mark and clock; portable ANSI palette.
            elif index == 3 or line.startswith('+'):
                code = '36'
            elif any(word in lower for word in ('failed', 'reverted', 'error:', 'stop:')):
                code = '1;31'
            elif any(word in lower for word in ('retry', 'unavailable', 'awaiting', 'cooling')):
                code = '33'
            elif line.startswith('|>') or any(word in lower for word in ('confirmed', 'verified:')):
                code = '32'
            lines.append(f'\x1b[{code}m{line}\x1b[0m')
        return '\n'.join(lines)

    def render(self):
        while not self.done.is_set():
            if self.input_fd is not None and select.select([self.input_fd], [], [], 0)[0]:
                keys = os.read(self.input_fd, 32).decode('utf-8', errors='ignore')
                self.feed_keys(keys)
            elif self.input_buffer == '\x1b':
                self.input_buffer = ''
                self.handle_key('\x1b')
            size = shutil.get_terminal_size((80, 24))
            self.output.write('\x1b[H' + self.styled_frame(size.columns, size.lines).replace('\n', '\x1b[K\r\n') + '\x1b[K\x1b[J')
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
        if self.insights:
            self.insights.close()
        if self.enabled:
            self.stop()
            _CURRENT = None
            if self.privacy:
                print('Stopped. Privacy view kept log details hidden.')
            else:
                for line in list(self.events)[-8:]:
                    print(line)
