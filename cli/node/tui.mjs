import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline/promises';

export function uiEvent(event) {
  if (process.env.HYBURN_TUI_CHILD === '1') console.log('@HYBURN_UI@'+JSON.stringify(event));
}

export async function routeUI(options, argv) {
  if (options.cmd !== 'mine' || process.env.HYBURN_TUI_CHILD === '1') return;
  const interactive=process.stdin.isTTY && process.stdout.isTTY && process.stderr.isTTY;
  if (interactive && !options.plain) {
    const script=fileURLToPath(new URL('../tui.py',import.meta.url));
    process.on('SIGINT',()=>{}); // The shared UI receives the same terminal signal.
    const result=spawnSync('python3',[script,'--engine','node','--command',JSON.stringify([process.execPath,process.argv[1]]),'--',...argv],{stdio:'inherit'});
    if (result.error) throw new Error('Shared TUI needs Python 3.10+; install it or use --plain. No mining started.');
    process.exit(result.status ?? 130);
  }
  if (options.yes) return;
  if (!process.stdin.isTTY) throw new Error('Start choice requires a terminal; use --yes for intentional unattended mining.');
  const prompt=createInterface({input:process.stdin,output:process.stdout});
  try {
    if (!['y','yes'].includes((await prompt.question('Start mining? [y/N] ')).trim().toLowerCase())) {
      console.log('Mining not started. No new transactions sent.'); process.exit(0);
    }
  } finally { prompt.close(); }
}
