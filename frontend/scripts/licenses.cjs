// Preserve notices for the locked production dependency closure shipped in browser chunks.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8'));
const sections = ['Third-party browser dependencies\nGenerated from frontend/package-lock.json.\n'];
// CSS preflight and the module-preload helper ship even though their producers are build tools.
const browserHelpers = new Set(['node_modules/tailwindcss', 'node_modules/vite']);

// Vendored D3 copies carry their own notices below lib-vendor; nested packages are visited by lock path.
function notices(directory, prefix = '') {
  return fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name, 'en')).flatMap(entry => {
    const relative = path.join(prefix, entry.name), absolute = path.join(directory, entry.name);
    if (entry.isDirectory() && entry.name !== 'node_modules') return notices(absolute, relative);
    // Normalize whitespace only; retain every upstream license and copyright notice.
    return entry.isFile() && /^(license|licence|copying|notice)([._-]|$)/i.test(entry.name) ? [{ relative, text: fs.readFileSync(absolute, 'utf8').replace(/\r\n/g, '\n').replace(/[ \t]+$/gm, '').trim() }] : [];
  });
}

// Missing installed packages/notices fail the build instead of silently omitting attribution.
for (const [location, metadata] of Object.entries(lock.packages).sort(([a], [b]) => a.localeCompare(b, 'en'))) {
  if (!location || (metadata.dev && !browserHelpers.has(location))) continue;
  const files = notices(path.join(root, location));
  if (!files.length) throw new Error(`Missing license notice: ${location}`);
  // Lock paths distinguish nested versions without embedding machine-specific directories.
  sections.push(`${location.replace(/^node_modules\//, '')} @ ${metadata.version}\nDeclared license: ${metadata.license ?? 'See notices'}\n${files.map(file => `\n${file.relative}\n${file.text}\n`).join('')}`);
}
// This public text accompanies the minified code in every Python wheel, without local paths.
fs.writeFileSync(process.argv[2] ? path.resolve(root, process.argv[2]) : path.join(root, '../src/backtest/interfaces/web/static/third-party-licenses.txt'), sections.join('\n' + '='.repeat(72) + '\n\n'));
