import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import nextEnv from '@next/env';

const root = fileURLToPath(new URL('../', import.meta.url));
const expected = JSON.parse(readFileSync(new URL('../deployment.json', import.meta.url), 'utf8'));

export function validateDeployment(env) {
  if (env.VERCEL_ENV !== 'production' && env.HYBURN_PRODUCTION !== '1') return;
  const invalid = Object.entries(expected)
    .filter(([key, value]) => env[key] !== value)
    .map(([key]) => key);
  if (invalid.length) throw new Error(`Production deployment facts missing or incorrect: ${invalid.join(', ')}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  nextEnv.loadEnvConfig(root, false);
  validateDeployment(process.env);
  console.log('Deployment configuration checked.');
}
