'use strict';
// Retain the historical Node entrypoint while executing the replacement React regression suite.
const test = require('node:test');
const { execFileSync } = require('node:child_process');
const path = require('node:path');

test('React replacement covers exact values, marker binding, cancellation, stale selections and terminal history', () => {
  const root = path.resolve(__dirname, '../../frontend');
  const runner = path.join(root, 'node_modules/vitest/vitest.mjs');
  // Tests execute the real React/query code; they no longer emulate a retired vanilla DOM renderer.
  execFileSync(process.execPath, [runner, 'run', 'src/commands.test.ts', 'src/result-contracts.test.ts', 'src/interactions.test.tsx'], { cwd: root, stdio: 'inherit', timeout: 60_000 });
});
