"""Public Project X addresses and ABI helpers. No configured user wallet."""
from decimal import Decimal as D, getcontext
from web3 import Web3
getcontext().prec=100
RPC='https://rpc.hypurrscan.io'
WALLET=None
TOKEN=Web3.to_checksum_address('0xC02E218F52ea5D38759BB1AfA92C197eF30673B4')
WHYPE=Web3.to_checksum_address('0x5555555555555555555555555555555555555555')
FACTORY=Web3.to_checksum_address('0xFf7B3e8C00e57ea31477c32A5B52a58Eea47b072')
MANAGER=Web3.to_checksum_address('0xeaD19AE861c29bBb2101E834922B2FEee69B9091')
FEE=3000

def data(signature,types=(),values=()):
    return Web3.keccak(text=signature)[:4]+Web3().codec.encode(types,values)

def read(w,address,signature,types=(),values=(),outputs=('uint256',),block='latest'):
    result=w.eth.call({'to':address,'data':data(signature,types,values)},block_identifier=block)
    return w.codec.decode(outputs,result)

def require(condition,message):
    if not condition: raise RuntimeError(message)
