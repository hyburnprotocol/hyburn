"""Public, read-only view of the existing HYBURN pool; no wallet is loaded."""
from decimal import Decimal, getcontext
from web3 import Web3

getcontext().prec = 60
POOL = Web3.to_checksum_address('0x561fF10F136da03be56F31A53cd8D87f93694106')
TOKEN = Web3.to_checksum_address('0xC02E218F52ea5D38759BB1AfA92C197eF30673B4')
WHYPE = Web3.to_checksum_address('0x5555555555555555555555555555555555555555')


def show():
    w=Web3(Web3.HTTPProvider('https://rpc.hypurrscan.io',request_kwargs={'timeout':20}))
    if w.eth.chain_id!=999: raise RuntimeError('Expected HyperEVM chain 999')
    block=w.eth.block_number
    def read(address,sig,outputs,types=(),values=()):
        data=Web3.keccak(text=sig)[:4]+w.codec.encode(types,values)
        return w.codec.decode(outputs,w.eth.call({'to':address,'data':data},block_identifier=block))
    token0=read(POOL,'token0()',('address',))[0]
    token1=read(POOL,'token1()',('address',))[0]
    fee=read(POOL,'fee()',('uint24',))[0]
    if token0.lower()!=WHYPE.lower() or token1.lower()!=TOKEN.lower() or fee!=3000:
        raise RuntimeError('Unexpected pool configuration')
    sqrt=read(POOL,'slot0()',('uint160','int24','uint16','uint16','uint16','uint8','bool'))[0]
    price=Decimal('1e-9')/(Decimal(sqrt)/2**96)**2
    print('\nHYBURN / PROJECT X POOL — READ ONLY')
    print(f'Block: {block}\nPool: {POOL}\nToken CA: {TOKEN}')
    print(f'Spot price: {price:.12f} HYPE / HYBURN\nFee: 0.3%')
    for label,token,decimals in [('HYBURN',TOKEN,9),('WHYPE',WHYPE,18)]:
        raw=read(token,'balanceOf(address)',('uint256',),('address',),(POOL,))[0]
        print(f'Pool {label} balance: {Decimal(raw)/10**decimals:.9f}')
    print('Pool balances are not a trade quote or a measure of active liquidity.')
    print('Use Project X with your own wallet to add a position in this existing pool.')
    print('https://www.prjx.com\nhttps://hyperevmscan.io/address/'+POOL)

if __name__=='__main__':
    try: show()
    except Exception as error: raise SystemExit('Pool read failed: '+str(error)+'. No transaction was sent.')
