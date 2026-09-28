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
            if ui:
                for key in ('Requested burn', 'Requested budget', 'Requested reserve', 'Reward claims', 'Session action'):
                    if key in ui.fields:
                        print(f'{key}: {ui.fields[key]}')
            print('Burns are irreversible. Gas is extra. Resume keeps the saved budget.')
            return input(label + '? [y/N] ').strip().lower() in ('y', 'yes')
        except EOFError:
            return False


def preview_start(ui, args):
    """Display requested options without loading a key, session or RPC."""
    def option(name, fallback):
        for i, value in enumerate(args):
            if value.startswith(name+'='):
                return value.split('=',1)[1]
            if value == name and i+1 < len(args):
                return args[i+1]
        return fallback
    ui.update(**{'Mode': 'STANDBY - no transactions sent',
                 'Requested burn': option('--amount', 'Saved value (required on first run)'),
                 'Requested budget': option('--budget', 'Saved value / --rounds limit'),
                 'Requested reserve': option('--reserve', 'Saved value / default 0.001 HYPE'),
                 'Reward claims': 'Automatic after start; claim gas is extra',
                 'Session action': 'NEW budget requested' if '--new-session' in args else 'Resume saved budget, or create first session'})


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
        self.enabled = enabled and os.environ.get('TERM') != 'dumb' and self.output.isatty() and self.errors.isatty() and size.columns >= 60 and size.lines >= 20
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
        self.clock_duration = 999
        self.clock_before_genesis = False
        self.market = None
        self.reduced_motion = os.environ.get('HYBURN_REDUCED_MOTION') == '1'
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
        self.names = None
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
            self.clock_duration = duration
            self.clock_before_genesis = timestamp < genesis

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
            if self.names is None and self.fields.get('Chain') == '999':
                from hl_names import Names
                self.names = Names(999)

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
            if key == 'F' and not self.awaiting_start and getattr(self, 'finish_callback', None):
                self.finish_callback()
                self.fields['Mode'] = 'FINISHING - no new burns; waiting for final claim'
                self.finish_callback = None
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
        if self.privacy and key not in public:
            return '[hidden]'
        if key == 'Wallet' and self.names:
            name = self.names.get(value)
            if name:
                return name + ' (' + value[:8] + '...' + value[-6:] + ')'
        return value

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

    def progress_rows(self, width):
        """Animate only an existing chain observation; never assume a new round."""
        if self.chain_clock is None:
            return ['ROUND CLOCK  Waiting for chain sync',
                    'Progress appears after the first verified chain read.']
        anchor, remaining, next_round = self.chain_clock
        age = max(0, time.monotonic() - anchor)
        left = max(0, remaining - age)
        if self.clock_before_genesis:
            return [f'GENESIS  Starts in ~{int(left + .999)}s' if left else 'GENESIS  Awaiting chain confirmation',
                    f'Local estimate | chain synced {int(age)}s ago']
        ratio = min(1, max(0, 1 - left / self.clock_duration))
        cells = max(10, min(48, width - 26))
        filled = int(ratio * cells)
        bar = '=' * filled + '-' * (cells - filled)
        window = re.match(r'(\d+)s before round end', self.fields.get('Send window', ''))
        schedule = ''
        if window and not self.privacy:
            window_seconds = int(window.group(1))
            marker = min(cells - 1, max(0, int(cells * (1 - window_seconds / self.clock_duration))))
            bar = bar[:marker] + '|' + bar[marker + 1:]
            schedule = f' | Burn window in ~{max(0, int(left-window_seconds))}s' if left > window_seconds else ' | Burn window reached'
        state = f'ends in ~{int(left)//60:02}:{int(left)%60:02}' if left else 'awaiting chain confirmation'
        return [f'ROUND {next_round-1}  [{bar}] {ratio:5.1%}',
                f'{state}{schedule} | sync {int(age)}s ago (estimate)']

    def market_line(self, width):
        """Read cached public market data, never make an API request while drawing."""
        if not self.market:
            return 'HYPE/USDC  -- | Spot price feed starts with the dashboard'
        data = self.market.snapshot()
        price, age = data.get('price'), data.get('age')
        if price is None:
            return 'HYPE/USDC  -- | SPOT | ' + data.get('status', 'unavailable').upper()
        label = 'STALE' if data.get('stale') else ('LIVE' if data.get('status') == 'live' else data.get('status','cached').upper())
        change = data.get('session_change_pct')
        change_text = f' | Session {change:+.2f}%' if change is not None else ''
        history = data.get('history', ())[-20:]
        chart = ''
        if width >= 110 and len(history) > 1:
            low, high = min(history), max(history)
            levels = '._-:=+*#'
            chart = ' ' + ''.join(levels[min(7, int((v-low)/(high-low)*7))] if high>low else '-' for v in history)
        return f'HYPE/USDC {price:,.4f} | SPOT MID | {label} {int(age or 0)}s{change_text}{chart}'

    def frame(self, width, height):
        width = max(1, width - 1)
        if width < 59 or height < 20:
            action = 'Standby: S starts, Q exits.' if self.awaiting_start else 'Ctrl-C stops; submitted transactions may still confirm.'
            return '\n'.join(line[:width] for line in [self.title + ' | ' + self.fields.get('Mode', 'Starting'), 'Compact terminal: resize to at least 60 x 20.', self.countdown(), action][:max(0,height)])
        with self.lock:
            status = self.status() if callable(self.status) else self.status
            if self.privacy:
                status = 'Privacy view enabled; execution settings unchanged.'
            tabs = ['1 Overview','2 Wallet','3 Activity','4 Round','5 History','6 Token','7 Leaders','? Help']
            if width < 100:
                tabs = ['1 Home','2 Wallet','3 Logs','4 Round','5 Yours','6 CA','7 Rank','?']
            if width < 75:
                tabs = ['1 Home','2 Wallet','3 Log','4 Round','5 Me','6 CA','7 All','?']
            tabs[self.page] = '[' + tabs[self.page] + ']'
            title = self.title
            if not self.privacy and self.names and self.fields.get('Wallet'):
                name = self.names.get(self.fields['Wallet'])
                if name:
                    title += ' | ' + (name if len(name) <= 24 else name[:21] + '...')
            lines = [title, '  '.join(tabs),
                     'Stats: ' + ('PAUSED' if self.stats_paused else 'ON DEMAND') +
                     ' | Privacy: ' + ('ON' if self.privacy else 'OFF') + ' | Engine: ' + self.fields.get('Engine','--')]
            lines += self.progress_rows(width)
            spinner = '.' if self.reduced_motion else '|/-\\'[int(time.monotonic()*4)%4]
            lines += [f'{spinner} {clean(status)}']
            footer = [self.market_line(width),
                      'S: START  Q: EXIT | No new submissions until start' if self.awaiting_start else
                      'Tab: pages  r: refresh  p: stats  v: privacy  F: finish/claim  ^C: exit']
            space = max(3, height-len(lines)-len(footer))
            if self.page == 0:
                if self.awaiting_start:
                    rows = ['REVIEW -> S: START -> UNLOCK -> VERIFY -> MINE',
                            'All requested amounts are HYPE. Burns are irreversible.',
                            'Transaction gas is extra.',
                            *[f'{key}: {self.display_field(key,self.fields[key])}' for key in
                              ('Requested burn','Requested budget','Requested reserve','Reward claims','Session action') if key in self.fields],
                            'Saved values are checked after unlocking.',
                            'First burn normally waits until 30s before round end.',
                            'Q exits without starting. Existing transactions may confirm.']
                    lines += self.box('BEFORE YOU START', rows, width, space)
                else:
                    keys = [('Mode','Status'),('Burn / transaction','Burn / transaction'),('Burn / round','Burn / round'),
                            ('Burn budget','Burn budget (gas extra)'),('Burn spending','Burn budget used'),
                            ('Available incl. gas','Available incl. gas'),('Session burned','Burned in saved session'),
                            ('Session gas','Gas paid in saved session'),('Session burns','Confirmed burns'),
                            ('Confirmed burns','Confirmed burns')]
                    rows = []
                    for key,label in keys:
                        if key in self.fields:
                            rows.append(f'{label:<27} {self.display_field(key,self.fields[key])}')
                    rows += ['Balances and rewards are snapshots. 2: wallet / costs.']
                    event_height = 5 if space >= 15 else 0
                    lines += self.box('MINING OVERVIEW', rows, width, space-event_height)
                    if event_height:
                        events = ['Log details hidden for sharing.'] if self.privacy else list(self.events)[-3:]
                        lines += self.box('RECENT ACTIVITY / 3: FULL LOG', events, width, event_height)
            elif self.page == 1:
                rows = [f'{key:<22} {self.display_field(key,value)}' for key,value in self.fields.items()]
                if self.names and 'Wallet' in self.fields:
                    rows.insert(1, f'{"Wallet address":<22} {self.display_field("Wallet address",self.fields["Wallet"])}')
                rows += ['Snapshots from last read. No refresh RPC.', 'Public miner budget: saved across restarts; gas extra.',
                         'Deploy console cap: saved; includes gas.']
                lines += self.box('WALLET / COSTS - j/k scroll, g top',rows[self.scroll:],width,space)
            elif self.page == 2:
                end = len(self.events)-self.scroll
                rows = ['Log details hidden for sharing.'] if self.privacy else list(self.events)[max(0,end-space+2):end]
                lines += self.box('ACTIVITY - k older, j newer, g latest',rows,width,space)
            elif self.page in (3,4,6):
                snapshot = self.snapshots.get(self.page)
                heading = {3:'CURRENT ROUND / BURN RANK',4:'MY ROUND HISTORY',6:'ALL-TIME / MINING PARTICIPATION'}[self.page]
                rows = ['Statistics PAUSED (p resumes; mining is unchanged)' if self.stats_paused else self.insight_messages.get(self.page,'Open this tab after starting to load statistics.')]
                if self.privacy:
                    rows = ['Public statistics only; personal rows and filters hidden.']
                if snapshot:
                    data,caption,note,updated = snapshot
                    if self.privacy:
                        if self.page == 4:
                            rows = ['Personal round history hidden for sharing.']
                        else:
                            rows += textwrap.wrap(self.public_summaries.get(self.page) or 'Public summary not available yet.',width=max(1,width-2))
                            rows += [f'Updated {int(time.monotonic()-updated)}s ago (snapshot, not live)',
                                     'Wallets are not people. No personal wallet markers shown.']
                    else:
                        rows += [caption,f'Updated {int(time.monotonic()-updated)}s ago (snapshot, not live)',note]
                    if not self.privacy and self.page in self.tables:
                        self.tables[self.page].names = self.names
                        rows += self.tables[self.page].render(width-2,space-2-len(rows),self.privacy)
                    elif not self.privacy:
                        rows += data[self.scroll:]
                lines += self.box(heading,rows,width,space)
            elif self.page == 5:
                rows = ['Token CA (from the miner contract):',self.fields.get('Token CA','Not read yet'),
                        'Miner contract (different from the token):',self.fields.get('Miner','--'),
                        'Chain: '+self.fields.get('Chain','--'),'Verify the address on this chain, not just the name.']
                lines += self.box('TOKEN IDENTITY',rows,width,space)
            else:
                rows = ['1 Overview  2 Wallet  3 Activity  4 Current round',
                        '5 Your history  6 Token identity  7 All-time leaders',
                        'Tab changes page. j/k or arrows scroll. g resets scroll.',
                        'Tables: / search, o sort, m your wallet, f claim status.',
                        'c clears filters. PgUp/PgDn move five rows.',
                        'r refreshes statistics (cooldowns apply).',
                        'p pauses STATISTICS ONLY, not mining. v toggles privacy.',
                        'F finishes mining and claims when eligible; gas applies.',
                        'Ctrl-C stops immediately; pending transactions may confirm.',
                        'Navigation never signs or changes spending.',
                        'Progress is a local estimate, not chain confirmation.',
                        'Spot prices are informational; they never control mining.',
                        'Privacy cannot hide window titles or shell scrollback.',
                        'HYBURN_MARKET_FEED=0 disables the public price stream.',
                        'HYBURN_REDUCED_MOTION=1 reduces animation. NO_COLOR disables color.',
                        'Use --plain for persistent line logs. Keep gas for claims.']
                lines += self.box('HELP - j/k scroll, g top',rows[self.scroll:],width,space)
            lines += footer
            return '\n'.join(line[:width] for line in lines[:height])

    def styled_frame(self, width, height):
        """Semantic dark/mint theme, with portable ANSI and NO_COLOR fallbacks."""
        frame = self.frame(width,height)
        if not self.color:
            return frame
        truecolor = os.environ.get('COLORTERM','').lower() in ('truecolor','24bit')
        palette = {'text':(229,238,233),'mint':(151,252,228),'muted':(155,173,165),
                   'border':(41,66,57),'warning':(233,189,117),'error':(240,128,128)}
        ansi = {'text':'37','mint':'1;36','muted':'37','border':'36','warning':'33','error':'1;31'}
        lines = []
        for index,line in enumerate(frame.splitlines()):
            lower = line.lower()
            role = 'text'
            if index <= 1 or line.startswith('ROUND '):
                role = 'mint'
            elif line.startswith('+'):
                role = 'mint' if any(c.isalpha() for c in line) else 'border'
            elif any(word in lower for word in ('failed','reverted','error:','stop:')):
                role = 'error'
            elif any(word in lower for word in ('retry','unavailable','stale','awaiting','cooling')):
                role = 'warning'
            elif 'confirmed' in lower or 'verified:' in lower:
                role = 'mint'
            elif index == 2 or 'sync ' in lower or line.startswith('HYPE/USDC'):
                role = 'muted'
            code = ('38;2;'+';'.join(map(str,palette[role]))+';48;2;7;20;17') if truecolor else ansi[role]
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
            self.done.wait(1.0 if self.reduced_motion else 0.25)

    def start(self):
        self.done.clear()
        if self.market is None:
            from market_feed import MarketFeed
            self.market = MarketFeed()
            self.market.start()
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
                if self.market:
                    self.market.stop()
                self.stop()
                _CURRENT = None
                raise
        return self

    def __exit__(self, *_):
        global _CURRENT
        if self.market:
            self.market.stop()
        if self.names:
            self.names.close()
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
