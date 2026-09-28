# Your first HYBURN mining session

This guide uses the default Python engine. You do not need Node.js, Go, Rust,
Foundry, Vercel or a contract deployment. Mining spends real HYPE irreversibly;
HYBURN rewards have no guaranteed price or liquidity.

## 1. Prepare the computer

Use Terminal on macOS, a Linux terminal, or a WSL Linux terminal on Windows.
Native Windows PowerShell is not the command environment used by this guide.
Run each line separately; do not copy the Markdown fences or a shell prompt.

```sh
git --version
python3 --version
python3 -m pip --version
```

You need Git and Python 3.10 or newer with pip and venv. If a command is missing,
install Git/Python for your operating system first. On macOS, `git --version`
may open Apple's developer-tools installer. On Linux, your distribution may
package pip and venv separately. Reopen your terminal after installing runtimes.

Official installation pages: [Python](https://www.python.org/downloads/),
[Git](https://git-scm.com/downloads/), and
[Windows WSL](https://learn.microsoft.com/en-us/windows/wsl/install).
On Windows, install Python/Git inside WSL for these commands, not only on Windows.

## 2. Download and enter the project

```sh
git clone https://github.com/hyburnprotocol/hyburn.git
cd hyburn
./cli/hyburn setup
```

The first run installs Python dependencies automatically; wait for it to finish.
If you already cloned the project, enter that existing folder instead of cloning
again. All commands below assume you are in the folder containing README.md and cli/.

## 3. Connect a dedicated wallet

There is no Rabby/browser connection popup. Use a separate software-wallet account
for mining. A public address cannot sign. Hardware-wallet signing is not supported.
Never send your private key or password to another person or paste them into chat.

At `Keystore path`, press Enter if you do not already have an Ethereum JSON
keystore. Export the private key of your dedicated account using your wallet's
own interface, and enter it at the hidden private-key prompt. Do not enter a seed
phrase. Input shows no characters or dots; this is normal. Press Enter to submit.

Choose a new password of at least 12 characters and repeat it. This encrypts the
local keystore; it is not necessarily your browser wallet password. Check the
printed address against the account you chose. Back up the encrypted keystore
and password separately. Setup saves a connection profile automatically and
does not send funds. Repeating setup never overwrites an existing profile.

## 4. Fund and check

Fund the printed address with native HYPE **on HyperEVM, chain 999**. HYPE on
HyperCore, WHYPE and HYBURN cannot pay native gas here. Check the destination
network in your wallet; never assume a similarly named network is correct.

Our example allows two burns of 0.000999 HYPE: 0.001998 HYPE in total.
You need that amount **plus variable transaction gas plus a 0.001 HYPE reserve**.
There is no fixed gas-inclusive funding amount. The miner checks affordability
before sending; a reserve is not a promise that all future gas prices are covered.

Copy the exact status command printed by setup (it includes your public address).
Optionally simulate a burn:

```sh
./cli/hyburn burn 0.000999 --dry-run
```

Enter the keystore password when asked. This simulation does not burn HYPE or
reserve a reward. Do not remove `--dry-run` unless you intend an immediate burn.

## 5. Start a bounded session

```sh
./cli/hyburn mine --amount 0.000999 --budget 0.001998
```

Read the requested settings on the start screen. Press S to continue or Q to exit.
A small/plain terminal asks `[y/N]`; Enter alone cancels. After S, enter your
keystore password and wait for connection checks. Gas is additional to the budget.

The first burn normally waits until 30 seconds before the round ends. A countdown
of almost 999 seconds is normal. Keep the terminal open and computer awake.
`LIVE` means live execution mode; a burn is confirmed only after its receipt.
The countdown is a local estimate, not proof of chain confirmation.

The budget survives restarts. After the last burn, the miner waits for its round
to finish and automatically claims the final reward. Leave it open until it stops.
Tab 6 shows the token CA; HYBURN may need to be imported into your wallet by that
address before its balance appears. Do not use the Miner address as the token CA.

## 6. Stop, resume and update

Ctrl-C stops the process; an already submitted transaction can still confirm.
In a later terminal, enter the same project folder and run:

```sh
./cli/hyburn mine
```

No repeated amount/budget is needed. An exhausted budget does not refill on
restart or after a wallet deposit. See [sessions](SESSION.md) before explicitly
authorizing another budget. Run only one miner per wallet.

To update, stop the miner, then run from the project folder:

```sh
git pull --ff-only
./cli/hyburn mine
```

If Git reports local changes or a conflict, stop and inspect it; do not delete
wallet files or reset the repository blindly. Setup is not needed again.

## If something goes wrong

| Message/situation | Next step |
| --- | --- |
| `./cli/hyburn: No such file` | Enter the downloaded hyburn folder first. |
| Python/pip/venv missing | Install the named prerequisite, reopen the terminal, retry setup. |
| Wrong key/password format | Correct the indicated input and rerun setup; never share the key. |
| Cannot unlock keystore | Check its password and file. Do not delete the keystore. |
| Balance below needed amount | Check HyperEVM native HYPE, burn value, gas and reserve. |
| RPC retry / connection failure | Wait for bounded retries; if stopped, resume with the same command. Do not reset the budget. |
| Wallet already in use | Stop the other miner using this wallet. |
| Budget reached | Normal completion; let final reward claiming finish. |

Use [TUI controls](TUI.md) for rankings, history and screenshot privacy.
Python, Node.js, Go and Rust share the launcher and wallet profile, but only
Python is required for this beginner path. Never post keys, passwords or raw logs
containing authenticated RPC URLs when asking for help.

## Return without remembering commands

From the project folder, run:

```sh
./hyburn
```

Choose an engine, connect a wallet, or open the mining dashboard from the menu.
The dashboard still asks before starting mining. The pool overview is read-only
and requires no wallet. Creating or managing liquidity is separate from mining;
never assume the mining spending budget covers liquidity deposits.
