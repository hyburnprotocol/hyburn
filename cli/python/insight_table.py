"""Pure terminal table navigation. No filesystem, RPC, keys or transaction access."""
from decimal import Decimal


def amount(value, decimals):
    if value is None:
        return '--'
    number = Decimal(value)/Decimal(10**decimals)
    text = f'{number:.9f}'
    return text if len(text) <= 16 else f'{number:.5E}'


class InsightTable:
    def __init__(self, page, own=''):
        self.page, self.own = page, own.lower()
        self.records = []
        self.selected = 0
        self.offset = 0
        self.query = ''
        self.editing = None
        self.mine_only = False
        self.status = 'ALL'
        self.sort = 'round' if page == 4 else 'burned'
        self._view = None

    def set_records(self, records, own):
        old = self.view()
        identifier = self.identity(old[self.selected]) if old and self.selected < len(old) else None
        self.records = [dict(row) for row in records]
        self.own = own.lower()
        self._view = None
        rows = self.view()
        self.selected = next((i for i,r in enumerate(rows) if self.identity(r)==identifier), min(self.selected,max(0,len(rows)-1)))

    def identity(self, row):
        return row.get('account', row.get('round'))

    def view(self):
        if self._view is not None:
            return self._view
        ordered = sorted(self.records, key=lambda r:(-(r.get(self.sort) or 0), str(self.identity(r))))
        result = []
        for rank,row in enumerate(ordered,1):
            own = row.get('account','').lower() == self.own
            text = ' '.join(str(row.get(k,'')) for k in ('account','round','status')).lower()
            if own:
                text += ' me you'
            if self.query.lower() not in text or (self.mine_only and not own):
                continue
            if self.page==4 and self.status != 'ALL' and row['status'] != self.status:
                continue
            result.append(dict(row, rank=rank, own=own))
        self._view = result
        return result

    def handle(self, key):
        if self.editing is not None:
            if key == '\x1b':
                self.editing = None
            elif key in ('\r','\n'):
                self.query = self.editing
                self.editing = None
                self._view = None
                self.selected = self.offset = 0
            elif key in ('\x7f','\b'):
                self.editing = self.editing[:-1]
            elif len(key)==1 and key.isascii() and key.isprintable() and len(self.editing)<64:
                self.editing += key
            return True
        if key == '/':
            self.editing = self.query
        elif key == 'o':
            choices = ['round','burned','claimed'] if self.page==4 else (['burned','rounds','claimed','txs'] if self.page==6 else ['burned','txs'])
            self.sort = choices[(choices.index(self.sort)+1)%len(choices)]
            self._view = None
            self.selected = self.offset = 0
        elif key == 'm' and self.page != 4:
            self.mine_only = not self.mine_only
            self._view = None
            self.selected = self.offset = 0
        elif key == 'f' and self.page == 4:
            choices=['ALL','OPEN','CLAIMABLE','CLAIMED']
            self.status=choices[(choices.index(self.status)+1)%len(choices)]
            self._view = None
            self.selected = self.offset = 0
        elif key == 'c':
            self.query = ''
            self.mine_only = False
            self.status = 'ALL'
            self._view = None
            self.selected = self.offset = 0
        elif key in ('j','\x1b[B','k','\x1b[A','g','G','\x1b[5~','\x1b[6~','\x1b[H','\x1b[F'):
            end = max(0,len(self.view())-1)
            if key in ('g','\x1b[H'):
                self.selected=0
            elif key in ('G','\x1b[F'):
                self.selected=end
            else:
                delta = {'j':1,'\x1b[B':1,'k':-1,'\x1b[A':-1,'\x1b[5~':-5,'\x1b[6~':5}[key]
                self.selected=max(0,min(end,self.selected+delta))
        else:
            return False
        return True

    def render(self, width, height, privacy=False):
        if privacy:
            return ['Personal wallet rows and filters hidden for sharing.'][:height]
        rows = self.view()
        if self.editing is not None:
            controls = 'Search (Enter apply / Esc cancel): ' + ('[hidden]' if privacy else self.editing) + '_'
        else:
            names={'burned':'HYPE','claimed':'claimed HYBURN','rounds':'rounds','txs':'burn txs','round':'round'}
            query = '[hidden]' if privacy and self.query else self.query
            controls = f'Sort: {names[self.sort]} v | ' + (f'Status: {self.status}' if self.page==4 else f'Me only: {"ON" if self.mine_only else "OFF"}')
            if query:
                controls += ' | /'+query
        if self.page==4:
            header='   Round       HYPE burned   Txs  Status         Claimed HYBURN'
        elif self.page==6:
            header='   Rank Wallet               HYPE burned Rounds     Claimed HYBURN'
        else:
            header='   Rank Wallet                      HYPE burned    Share   Txs'
        count=max(1,height-5)
        self.selected=min(self.selected,max(0,len(rows)-1))
        self.offset=min(self.offset,self.selected)
        if self.selected>=self.offset+count:
            self.offset=self.selected-count+1
        body=[]
        for i,r in enumerate(rows[self.offset:self.offset+count],self.offset):
            pointer='>' if i==self.selected else ' '
            if self.page==4:
                burned=amount(r['burned'],18) if not privacy else '[hidden]'
                claimed=amount(r['claimed'],9) if not privacy else '[hidden]'
                body.append(f"{pointer} {r['round']:>6} {burned:>17} {r['txs']:>5}  {r['status']:<10} {claimed:>17}")
            else:
                address=r['account'][:8]+'...'+r['account'][-6:]
                if privacy:
                    address='YOU' if r['own'] else 'WALLET'
                burned=amount(r['burned'],18) if not privacy else '[hidden]'
                mark='*' if r['own'] else ' '
                if self.page==6:
                    claimed=amount(r['claimed'],9) if not privacy else '[hidden]'
                    body.append(f"{pointer}{mark}{r['rank']:>5} {address:<17} {burned:>15} {r['rounds']:>6} {claimed:>18}")
                else:
                    body.append(f"{pointer}{mark}{r['rank']:>5} {address:<21} {burned:>17} {r['share']:>8} {r['txs']:>5}")
        if not rows:
            body=['No matching records. c: clear filters.' if self.records else 'No indexed records yet; check coverage above.']
        body += [''] * max(0,count-len(body))
        selected=rows[self.selected] if rows else None
        if privacy:
            detail='Privacy view: addresses and amounts hidden.'
        elif selected and self.page!=4:
            detail=selected['account']+f' | burn txs: {selected["txs"]}'
        elif selected:
            detail=f"Round {selected['round']} | Claim amount is received rewards, not holdings."
        else:
            detail='Waiting for indexed records; check coverage above.'
        footer=f'{self.selected+1 if rows else 0}/{len(rows)} visible | j/k PgUp/Dn | / search  o sort  c clear'
        return ([controls,header,'-'*min(width,len(header))]+body+[detail,footer])[:height]
