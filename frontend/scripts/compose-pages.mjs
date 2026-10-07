// Combine two separately built public exports without merging their data or identity.
import { createHash } from 'node:crypto';
import { lstat, mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const publicFile = /^(?:assets\/[A-Za-z0-9_.-]+\.(?:js|css)|demo-data\/(?:manifest\.(?:json|sha256)|responses\/[0-9a-f]{64}\.json)|\.vite\/manifest\.json|index\.html|theme\.js|third-party-licenses\.txt|\.nojekyll)$/;
const digestPattern = /^[0-9a-f]{64}$/;

async function files(directory, prefix = '') {
  if (!(await lstat(directory)).isDirectory()) throw new Error('Distribution must be a physical directory.');
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const name = prefix + entry.name;
    if (entry.isSymbolicLink()) throw new Error('Links cannot enter Pages output.');
    if (entry.isDirectory()) result.push(...await files(path.join(directory, entry.name), name + '/'));
    else if (entry.isFile()) result.push(name);
    else throw new Error('Only regular public files are supported.');
  }
  return result.sort();
}

async function checkedBytes(root, entry) {
  const filename = path.join(root, entry.file);
  const info = await lstat(filename);
  if (!info.isFile() || info.size !== entry.bytes) throw new Error('Distribution file size/type mismatch: ' + entry.file);
  const bytes = await readFile(filename);
  if (hash(bytes) !== entry.sha256) throw new Error('Distribution file hash mismatch: ' + entry.file);
  return bytes;
}

export async function verifyDistribution(directory, synthetic) {
  const root = path.resolve(directory);
  const names = await files(root);
  const inventoryRaw = await readFile(path.join(root, 'distribution.json'));
  if (inventoryRaw.length > 4 * 1024 ** 2) throw new Error('Distribution inventory is too large.');
  const inventory = JSON.parse(inventoryRaw);
  if (inventory.schema !== 'backtest.demo-distribution/v1' || inventory.synthetic !== synthetic || !Array.isArray(inventory.files) || inventory.files.length > 10000) throw new Error('Wrong distribution profile or schema.');
  const expected = new Set(['distribution.json']);
  let total = 0;
  for (const entry of inventory.files) {
    if (!publicFile.test(entry.file) || expected.has(entry.file) || !Number.isSafeInteger(entry.bytes) || entry.bytes < 0 || entry.bytes > 8 * 1024 ** 2 || !digestPattern.test(entry.sha256)) throw new Error('Invalid public file inventory.');
    expected.add(entry.file);
    total += entry.bytes;
    if (total > 320 * 1024 ** 2) throw new Error('Distribution exceeds the public export bound.');
    await checkedBytes(root, entry);
  }
  if (names.length !== expected.size || names.some(name => !expected.has(name))) throw new Error('Unlisted public files in distribution.');
  const manifestRaw = await readFile(path.join(root, 'demo-data/manifest.json'));
  const digest = (await readFile(path.join(root, 'demo-data/manifest.sha256'), 'utf8')).trim();
  if (!digestPattern.test(digest) || hash(manifestRaw) !== digest) throw new Error('Corpus manifest hash mismatch.');
  const manifest = JSON.parse(manifestRaw);
  if (manifest.synthetic !== synthetic || manifest.schema !== (synthetic ? 'backtest.static-demo/v1' : 'backtest.static-history/v1')) throw new Error('Corpus truth label does not match distribution.');
  if (!manifest.responses || typeof manifest.responses !== 'object' || Array.isArray(manifest.responses)) throw new Error('Invalid corpus response map.');
  const records = Object.entries(manifest.responses);
  if (records.length > (synthetic ? 2048 : 8192)) throw new Error('Too many corpus responses.');
  const allowedData = new Set(['demo-data/manifest.json', 'demo-data/manifest.sha256']);
  let responseBytes = 0;
  for (const [route, record] of records) {
    if (!route.startsWith('/api/v1/') || /[#\\\s]/.test(route) || route.includes('..') || route.includes('://') || !digestPattern.test(record.sha256) || record.file !== `responses/${record.sha256}.json` || !Number.isSafeInteger(record.bytes) || record.bytes < 0 || record.bytes > 2 * 1024 ** 2) throw new Error('Invalid corpus response record.');
    const filename = 'demo-data/' + record.file;
    if (!expected.has(filename)) throw new Error('Corpus response is not in the distribution.');
    const bytes = await checkedBytes(root, { ...record, file: filename });
    JSON.parse(bytes);
    if (/(?:\/Users\/|\/private\/|\/tmp\/|\.env\b|secret_ref|password|127\.0\.0\.1|localhost)/i.test(bytes.toString())) throw new Error('Non-exportable local metadata in corpus.');
    responseBytes += bytes.length;
    allowedData.add(filename);
  }
  if (responseBytes !== manifest.response_bytes || responseBytes > (synthetic ? 16 : 256) * 1024 ** 2) throw new Error('Invalid corpus response total.');
  if (names.some(name => name.startsWith('demo-data/') && !allowedData.has(name))) throw new Error('Unreferenced corpus data.');
  if (!expected.has('index.html') || !expected.has('.nojekyll')) throw new Error('Incomplete static distribution.');
  const html = await readFile(path.join(root, 'index.html'), 'utf8');
  if (!html.includes('Content-Security-Policy') || !html.includes('form-action &#39;none&#39;') && !html.includes("form-action 'none'")) throw new Error('Demo CSP missing.');
  return { root, files: inventory.files, manifestSha256: digest, inventoryRaw };
}

export async function composePages(historicalDirectory, copyBuyDirectory, outputDirectory) {
  const output = path.resolve(outputDirectory);
  try { await lstat(output); throw new Error('Output already exists; use a new Pages directory.'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const historical = await verifyDistribution(historicalDirectory, false);
  const copyBuy = await verifyDistribution(copyBuyDirectory, true);
  if ([historical.root, copyBuy.root].some(root => output === root || output.startsWith(root + path.sep))) throw new Error('Output must be outside both input distributions.');
  const staging = await mkdtemp(path.join(path.dirname(output), '.pages-compose-'));
  try {
    const entries = [];
    for (const [distribution, prefix] of [[historical, ''], [copyBuy, 'copy-buy/']]) {
      for (const entry of distribution.files) {
        const bytes = await checkedBytes(distribution.root, entry);
        const file = prefix + entry.file;
        await mkdir(path.dirname(path.join(staging, file)), { recursive: true });
        await writeFile(path.join(staging, file), bytes, { flag: 'wx' });
        entries.push({ ...entry, file });
      }
    }
    const childInventory = 'copy-buy/distribution.json';
    await writeFile(path.join(staging, childInventory), copyBuy.inventoryRaw, { flag: 'wx' });
    entries.push({ file: childInventory, bytes: copyBuy.inventoryRaw.length, sha256: hash(copyBuy.inventoryRaw) });
    const inventory = {
      schema: 'backtest.pages-distribution/v1',
      profiles: [
        { path: './', synthetic: false, manifest_sha256: historical.manifestSha256 },
        { path: 'copy-buy/', synthetic: true, manifest_sha256: copyBuy.manifestSha256 },
      ],
      files: entries.sort((a, b) => a.file.localeCompare(b.file)),
    };
    await writeFile(path.join(staging, 'distribution.json'), JSON.stringify(inventory), { flag: 'wx' });
    await rename(staging, output);
    return inventory;
  } catch (error) {
    await rm(staging, { recursive: true, force: true });
    throw error;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 5) throw new Error('Usage: node compose-pages.mjs <historical-dist> <copy-buy-dist> <new-output-dir>');
  const inventory = await composePages(...process.argv.slice(2));
  console.log(`Composed verified Pages output: historical root + synthetic copy-buy/, ${inventory.files.length} public files.`);
}
