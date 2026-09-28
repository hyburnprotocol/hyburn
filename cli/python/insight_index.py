"""Rebuildable public-event index. Entirely separate from signing/session journals."""
import json
import os
from pathlib import Path
import sqlite3
import time


class EventIndex:
    VERSION = 1

    def __init__(self, path, identity, start):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.identity = json.dumps(identity, sort_keys=True)
        self.rebuilt = False
        try:
            self._open(start)
        except (sqlite3.DatabaseError, ValueError, TypeError) as error:
            if getattr(self, 'db', None):
                self.db.close()
            if isinstance(error, sqlite3.OperationalError):
                raise  # Locked/unwritable databases are not corrupt; never rename them.
            # Only this disposable analytics cache is rebuilt; never a mining journal.
            suffix=f'.invalid-{time.time_ns()}'
            for tail in ('','-journal','-wal','-shm'):
                source=Path(str(self.path)+tail)
                if source.exists():
                    source.rename(Path(str(self.path)+suffix+tail))
            self.rebuilt = True
            self._open(start)

    def _open(self, start):
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(self.path, timeout=1)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Invalid statistics cache')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                tx TEXT NOT NULL, idx INTEGER NOT NULL, block INTEGER NOT NULL,
                kind TEXT NOT NULL, round INTEGER NOT NULL, account TEXT NOT NULL,
                value TEXT NOT NULL, amount TEXT NOT NULL, PRIMARY KEY(tx,idx));
            CREATE INDEX IF NOT EXISTS events_block ON events(block);
            CREATE INDEX IF NOT EXISTS events_account ON events(account,block);
            CREATE TABLE IF NOT EXISTS wallets (
                account TEXT PRIMARY KEY, burned TEXT NOT NULL, claimed TEXT NOT NULL,
                rounds INTEGER NOT NULL, txs INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS wallet_rounds (
                account TEXT NOT NULL, round INTEGER NOT NULL, burned TEXT NOT NULL,
                PRIMARY KEY(account,round));
            CREATE TABLE IF NOT EXISTS wallet_txs (
                account TEXT NOT NULL, tx TEXT NOT NULL, PRIMARY KEY(account,tx));
            CREATE TABLE IF NOT EXISTS checkpoints (block INTEGER PRIMARY KEY, hash TEXT NOT NULL);
        ''')
        previous = self.get('identity')
        if previous is not None:
            if previous != self.identity or self.get('version') != str(self.VERSION):
                raise ValueError('Statistics identity/version mismatch')
            if int(self.get('start')) < 0 or int(self.get('end')) < int(self.get('start'))-1:
                raise ValueError('Invalid statistics cursor')
        else:
            with self.db:
                for key, value in [('identity', self.identity), ('version', self.VERSION),
                                   ('start', start if start is not None else 0),
                                   ('end', start-1 if start is not None else -1),
                                   ('origin_ready', int(start is not None))]:
                    self.put(key, value)

    def get(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    @property
    def start(self):
        return int(self.get('start'))

    @property
    def end(self):
        return int(self.get('end'))

    def checkpoints(self, limit=8):
        return self.db.execute('SELECT block,hash FROM checkpoints ORDER BY block DESC LIMIT ?', (limit,)).fetchall()

    def _apply(self, event):
        account = event['account']
        row = self.db.execute('SELECT * FROM wallets WHERE account=?', (account,)).fetchone()
        burned, claimed, rounds, txs = (int(row['burned']), int(row['claimed']), row['rounds'], row['txs']) if row else (0, 0, 0, 0)
        if event['kind'] == 'burn':
            value = int(event['value'])
            burned += value
            previous = self.db.execute('SELECT burned FROM wallet_rounds WHERE account=? AND round=?',
                                       (account, event['round'])).fetchone()
            if previous is None:
                rounds += 1
            round_value = (int(previous[0]) if previous else 0) + value
            self.db.execute('INSERT OR REPLACE INTO wallet_rounds VALUES (?,?,?)',
                            (account, event['round'], str(round_value)))
            added = self.db.execute('INSERT OR IGNORE INTO wallet_txs VALUES (?,?)', (account, event['tx'])).rowcount
            txs += added
        else:
            claimed += int(event['amount'])
        self.db.execute('INSERT OR REPLACE INTO wallets VALUES (?,?,?,?,?)',
                        (account, str(burned), str(claimed), rounds, txs))

    def append(self, start, end, block_hash, events):
        """Atomic, idempotent range commit. Concurrent readers may share this cache."""
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.end != start-1:
                return False  # Another worker committed first; re-read its cursor.
            for e in events:
                if not start <= e['block'] <= end or e['kind'] not in ('burn', 'claim'):
                    raise ValueError('Event outside requested range')
                if int(e['value']) < 0 or int(e['amount']) < 0:
                    raise ValueError('Negative event value')
                values = (e['tx'], e['idx'], e['block'], e['kind'], e['round'], e['account'], str(e['value']), str(e['amount']))
                added = self.db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?)', values).rowcount
                if added:
                    self._apply(e)
            self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?)', (end, block_hash))
            self.put('end', end)
        return True

    def rollback(self, height):
        """Remove orphaned events, rebuilding only affected wallets in one transaction."""
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            affected = [r[0] for r in self.db.execute('SELECT DISTINCT account FROM events WHERE block>?', (height,))]
            self.db.execute('DELETE FROM events WHERE block>?', (height,))
            self.db.execute('DELETE FROM checkpoints WHERE block>?', (height,))
            for account in affected:
                for table in ('wallets', 'wallet_rounds', 'wallet_txs'):
                    self.db.execute(f'DELETE FROM {table} WHERE account=?', (account,))
                rows = self.db.execute('SELECT * FROM events WHERE account=? ORDER BY block,idx', (account,)).fetchall()
                for row in rows:
                    self._apply(row)
            self.put('end', max(self.start-1, height))

    def wallets(self):
        result = []
        for row in self.db.execute('SELECT * FROM wallets'):
            if int(row['burned']):
                result.append(dict(account=row['account'], burned=int(row['burned']),
                                   claimed=int(row['claimed']), rounds=row['rounds'], txs=row['txs']))
        return result

    def snapshot(self):
        # Cursor and totals must come from the same read transaction when other
        # wallets/engines are indexing this contract concurrently.
        with self.db:
            self.db.execute('BEGIN')
            return self.start, self.end, self.wallets()

    def close(self):
        self.db.close()
