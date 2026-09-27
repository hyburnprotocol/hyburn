#!/usr/bin/env python3
"""Import a dedicated mining key into an encrypted Ethereum keystore, entirely offline."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
from eth_account import Account


def write_keystore(path, key, password):
    if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{64}', key):
        raise ValueError('Enter a 32-byte hex private key, not a recovery phrase.')
    try:
        account = Account.from_key(key)
    except Exception:
        raise ValueError('Invalid private key.') from None
    if len(password) < 12:
        raise ValueError('Use a keystore password of at least 12 characters.')
    # Encrypt before creating the destination, and never replace an existing wallet.
    encrypted = Account.encrypt(account.key, password)
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(encrypted, stream)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return account.address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path.home() / '.hyburn/miner.keystore.json')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error('Run interactively in a terminal; do not pipe a private key.')
    if args.out.expanduser().exists():
        parser.error('Destination already exists; choose another --out path.')
    print('Offline wallet import. No network requests or transactions.')
    print('Use a dedicated mining account. Input is hidden; never enter a seed phrase.')
    key = getpass.getpass('Private key: ').strip()
    password = getpass.getpass('New keystore password (12+ characters): ')
    confirmation = getpass.getpass('Repeat password: ')
    if password != confirmation:
        raise SystemExit('Passwords do not match. No file created.')
    try:
        address = write_keystore(args.out, key, password)
    except FileExistsError:
        raise SystemExit('Destination already exists. Nothing overwritten.') from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    finally:
        del key, password, confirmation
    print(f'Address: {address}')
    print(f'Encrypted keystore: {args.out.expanduser()}')
    print('Check this address against your wallet. Back up the encrypted file and its password separately.')
    print('No funds moved. Fund this address on HyperEVM (chain 999) with HYPE for burns plus gas.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('\nCancelled.')
