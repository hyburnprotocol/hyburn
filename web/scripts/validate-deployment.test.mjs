import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateDeployment } from './validate-deployment.mjs';

const facts = JSON.parse(readFileSync(new URL('../deployment.json', import.meta.url), 'utf8'));
test('contributors can build without production settings', () => validateDeployment({}));
test('production accepts the canonical deployment', () => validateDeployment({ ...facts, VERCEL_ENV: 'production' }));
test('production rejects every missing or changed fact', () => {
  for (const key of Object.keys(facts)) {
    const env = { ...facts, HYBURN_PRODUCTION: '1' };
    delete env[key];
    assert.throws(() => validateDeployment(env), new RegExp(key));
    env[key] = 'incorrect';
    assert.throws(() => validateDeployment(env), new RegExp(key));
  }
});
