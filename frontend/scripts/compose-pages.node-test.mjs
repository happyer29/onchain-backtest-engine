import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { composePages } from './compose-pages.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');

async function fixture(root, synthetic) {
  const body = Buffer.from(JSON.stringify({ example: synthetic ? 'copy-buy' : 'historical' }));
  const response = { file: `responses/${hash(body)}.json`, bytes: body.length, sha256: hash(body) };
  const manifest = Buffer.from(JSON.stringify({
    schema: synthetic ? 'backtest.static-demo/v1' : 'backtest.static-history/v1',
    synthetic, response_bytes: body.length, responses: { '/api/v1/example': response },
  }));
  const files = {
    'index.html': Buffer.from('<meta http-equiv="Content-Security-Policy" content="form-action &#39;none&#39;"><script src="./assets/main.js"></script>'),
    'assets/main.js': Buffer.from(`export const manifestDigest = '${hash(manifest)}';`),
    'demo-data/manifest.json': manifest,
    'demo-data/manifest.sha256': Buffer.from(hash(manifest)),
    ['demo-data/' + response.file]: body,
    '.nojekyll': Buffer.from(''),
  };
  const entries = [];
  for (const [file, bytes] of Object.entries(files)) {
    await mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await writeFile(path.join(root, file), bytes);
    entries.push({ file, bytes: bytes.length, sha256: hash(bytes) });
  }
  await writeFile(path.join(root, 'distribution.json'), JSON.stringify({ schema: 'backtest.demo-distribution/v1', synthetic, files: entries }));
  return hash(manifest);
}

async function context(t) {
  const root = await mkdtemp(path.join(tmpdir(), 'pages-composition-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const history = path.join(root, 'history'), copy = path.join(root, 'copy'), output = path.join(root, 'pages');
  const historyDigest = await fixture(history, false), copyDigest = await fixture(copy, true);
  return { root, history, copy, output, historyDigest, copyDigest };
}

test('composition preserves each corpus and inventories every nested public byte', async t => {
  const { history, copy, output, historyDigest, copyDigest } = await context(t);
  const before = await readFile(path.join(history, 'distribution.json'));
  const inventory = await composePages(history, copy, output);
  assert.deepEqual(inventory.profiles, [
    { path: './', synthetic: false, manifest_sha256: historyDigest },
    { path: 'copy-buy/', synthetic: true, manifest_sha256: copyDigest },
  ]);
  for (const entry of inventory.files) {
    const bytes = await readFile(path.join(output, entry.file));
    assert.equal(bytes.length, entry.bytes);
    assert.equal(hash(bytes), entry.sha256);
  }
  assert(inventory.files.some(entry => entry.file === 'copy-buy/distribution.json'));
  assert.equal(hash(await readFile(path.join(output, 'demo-data/manifest.json'))), historyDigest);
  assert.equal(hash(await readFile(path.join(output, 'copy-buy/demo-data/manifest.json'))), copyDigest);
  assert.deepEqual(await readFile(path.join(history, 'distribution.json')), before);
  await assert.rejects(composePages(history, copy, output), /already exists/);
});

test('swapping historical and synthetic profiles cannot replace the historical root', async t => {
  const { history, copy, output } = await context(t);
  await assert.rejects(composePages(copy, history, output), /profile/);
});

for (const kind of ['corrupt', 'unlisted', 'symlink', 'wrong-label']) {
  test(`rejects ${kind} input before publishing a composed directory`, async t => {
    const { history, copy, output } = await context(t);
    if (kind === 'corrupt') await writeFile(path.join(copy, 'assets/main.js'), 'corrupt');
    if (kind === 'unlisted') await writeFile(path.join(copy, 'operational.sqlite'), 'private');
    if (kind === 'symlink') await symlink(path.join(history, 'index.html'), path.join(copy, 'linked.html'));
    if (kind === 'wrong-label') {
      const inventoryPath = path.join(copy, 'distribution.json');
      const inventory = JSON.parse(await readFile(inventoryPath));
      const manifestPath = path.join(copy, 'demo-data/manifest.json');
      const manifest = JSON.parse(await readFile(manifestPath));
      manifest.synthetic = false;
      const bytes = Buffer.from(JSON.stringify(manifest));
      await writeFile(manifestPath, bytes);
      await writeFile(path.join(copy, 'demo-data/manifest.sha256'), hash(bytes));
      for (const entry of inventory.files.filter(entry => entry.file.startsWith('demo-data/manifest.'))) {
        const content = await readFile(path.join(copy, entry.file));
        entry.bytes = content.length; entry.sha256 = hash(content);
      }
      await writeFile(inventoryPath, JSON.stringify(inventory));
    }
    await assert.rejects(composePages(history, copy, output));
    await assert.rejects(readFile(path.join(output, 'distribution.json')), { code: 'ENOENT' });
  });
}
