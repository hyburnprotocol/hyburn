#!/usr/bin/env python3
"""One-time offline onboarding shared by the four public miners."""
import getpass
import json
import os
from pathlib import Path
import sys
from eth_account import Account
from mining_session import home, atomic_json
from wallet_setup import write_keystore

ALLOWED = ('HYBURN_RPC', 'HYBURN_MINER', 'HYBURN_CHAIN_ID', 'HYBURN_DEPLOY_BLOCK', 'HYBURN_KEYSTORE')

def load_profile():
    path = home() / 'config.json'
    if not path.exists():
        return
    try:
        values = json.loads(path.read_text())
        if not isinstance(values, dict):
            raise ValueError()
        for key in ALLOWED:
            if key == 'HYBURN_KEYSTORE' and os.environ.get('HYBURN_PRIVATE_KEY'):
                continue
            if key in values:
                if not isinstance(values[key], str):
                    raise ValueError()
                os.environ.setdefault(key, values[key])
    except Exception:
        raise SystemExit('Invalid ~/.hyburn/config.json; fix the connection profile before continuing.') from None


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Run setup in an interactive terminal.')
    path = home() / 'config.json'
    if path.exists():
        print(f'Connection profile already saved at {path}. Nothing overwritten.')
        return
    print('HYBURN / SETUP — offline; no transactions')
    print('Enter an existing Ethereum JSON keystore path, or press Enter to import a private key.')
    existing = input('Keystore path: ').strip()
    if existing:
        keystore = Path(existing).expanduser().resolve()
        password = getpass.getpass('Keystore password (not saved): ')
        try:
            account = Account.from_key(Account.decrypt(json.loads(keystore.read_text()), password))
            address = account.address
        except Exception:
            raise SystemExit('Cannot unlock keystore. No profile saved.') from None
        finally:
            del password
    else:
        keystore = home() / 'miner.keystore.json'
        if keystore.exists():
            raise SystemExit(f'Keystore already exists: {keystore}. Run setup again and enter that path.')
        key = getpass.getpass('Private key (hidden; not a seed phrase): ').strip()
        password = getpass.getpass('New keystore password (12+ characters): ')
        confirmation = getpass.getpass('Repeat password: ')
        try:
            if password != confirmation:
                raise SystemExit('Passwords do not match.')
            address = write_keystore(keystore, key, password)
        finally:
            del key, password, confirmation
    print(f'Wallet: {address}')
    print('Network: HyperEVM (999). Fund this address with native HYPE for burns and gas.')
    values = dict(HYBURN_RPC='https://rpc.hypurrscan.io', HYBURN_MINER='0x951258b9c1C625536c25A6ECe943aA75B0386250', HYBURN_CHAIN_ID='999', HYBURN_DEPLOY_BLOCK='47024793', HYBURN_KEYSTORE=str(keystore.resolve()))
    atomic_json(path, values)
    print(f'Saved connection profile: {path}. All four miners load it automatically.')
    print('First run: mine --amount 0.000999 --budget YOUR_BURN_BUDGET')
    print('After that: mine (same saved budget; password required, gas extra).')
    print('Back up the keystore and password separately. No funds moved.')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('\nCancelled.')
