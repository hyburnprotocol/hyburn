// Hidden terminal input only; no wallet or network access.
import { createInterface } from "node:readline";
import { Writable } from "node:stream";

export function promptPassword(question) {
  if (!process.stdin.isTTY || !process.stderr.isTTY) {
    return Promise.reject(new Error("Use an interactive terminal for the keystore password"));
  }
  return new Promise((resolve, reject) => {
    let muted = false, finished = false;
    const output = new Writable({
      write(chunk, encoding, done) {
        if (!muted) process.stderr.write(chunk);
        done();
      },
    });
    const rl = createInterface({ input: process.stdin, output, terminal: true });
    const finish = (value, error) => {
      if (finished) return;
      finished = true;
      muted = true;
      rl.close();
      process.stderr.write("\n");
      if (error) reject(error); else resolve(value);
    };
    rl.on("SIGINT", () => finish(null, new Error("Wallet unlock cancelled")));
    rl.on("close", () => { if (!finished) finish(null, new Error("Wallet unlock cancelled")); });
    rl.question(question, (answer) => finish(answer));
    muted = true;
  });
}
