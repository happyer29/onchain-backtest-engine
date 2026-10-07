import {readFileSync} from 'node:fs';
import {test,expect} from '@playwright/test';
const catalog=JSON.parse(readFileSync('demo-data/manifest.json','utf8'));
const url=(route:string)=>`./#${route}`;

test('the opening guide leads to strict Copy Buy and inspectable attempts without execution', async ({ page, baseURL }) => {
  const strict = catalog.runs.find((run: { mode: string; summary: { family: string } }) => run.mode === 'EXOGENOUS_REPLAY' && run.summary.family === 'PUMPFUN_COPY_BUY');
  const requests: { url: string; method: string }[] = [];
  page.on('request', request => requests.push({ url: request.url(), method: request.method() }));
  await page.goto('./');
  await expect(page.getByRole('heading', { name: 'Start here: one Copy Buy example' })).toBeVisible();
  await expect(page.locator('.demo-guide-steps > li')).toHaveCount(4);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'demo-test-results/copy-buy-guide-mobile.png', fullPage: true });
  if (!strict && !catalog.synthetic) {
    await expect(page.getByRole('link', { name: 'Open Copy Buy walkthrough (synthetic)', exact: true })).toHaveAttribute('href', './copy-buy/');
    await expect(page.getByRole('link', { name: 'Open strict replay result', exact: true })).toHaveCount(0);
    expect(requests.every(request => request.method === 'GET' && request.url.startsWith(baseURL!))).toBe(true);
    return;
  }
  expect(strict, 'A prepared strict Copy Buy result is present').toBeTruthy();
  await page.getByRole('link', { name: 'Open strict replay result', exact: true }).click();
  await expect(page).toHaveURL(new RegExp('/runs/' + strict.id)); await page.reload();
  await expect(page.getByText('Next: Trades → token or Details', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Trades', exact: true }).click();
  await page.getByRole('button', { name: /^Details / }).first().click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'Signal → decision → fill', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Back to the four-step guide', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Start here: one Copy Buy example' })).toBeVisible();
  expect(requests.every(request => request.method === 'GET' && request.url.startsWith(baseURL!))).toBe(true);
  expect(requests.some(request => new URL(request.url).pathname.includes('/api/'))).toBe(false);
});

test.describe('synthetic corpus', () => {
  test.skip(!catalog.synthetic, 'The current distribution contains historical data.');

test('project-path demo covers the complete graph, all levels, evidence and mode selection',async({page,baseURL})=>{
  const errors:string[]=[],requests:string[]=[];page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>requests.push(request.url()));
  await page.addInitScript(()=>window.addEventListener('securitypolicyviolation',event=>document.documentElement.setAttribute('data-csp-error',event.violatedDirective)));
  await page.goto(url('/research'));await page.reload();
  await expect(page.getByText('Demo · test data',{exact:true})).toBeVisible();
  await page.getByRole('link',{name:'Skip to content'}).focus();await page.keyboard.press('Enter');await expect(page.locator('#main')).toBeFocused();
  await expect(page.getByTestId('graph-counts')).toContainText('60 wallets');
  await expect(page.getByTestId('graph-counts')).toContainText('423 pairs');
  await expect(page.locator('.research-canvas canvas').first()).toBeVisible();
  await expect(page.getByRole('button',{name:'Fit graph'})).toBeEnabled();
  await page.locator('.research-graph-panel').screenshot({path:'demo-test-results/demo-graph.png'});
  await page.getByLabel('Show pairs with at least this many shared tokens').fill('3');await page.getByRole('button',{name:'Apply display filter'}).click();
  await expect(page.getByTestId('graph-filter-counts')).toContainText('420 shown + 3 hidden = 423 pairs');
  await page.getByRole('button',{name:'Show every pair'}).click();
  await page.getByRole('button',{name:/^Group 1 ·/}).click();await expect(page.getByTestId('graph-counts')).toContainText('internal pairs');
  await page.getByRole('button',{name:'All wallets in group'}).click();await page.locator('.research-list button').first().click();
  await expect(page.getByTestId('graph-counts')).toContainText('incident pairs');await page.getByLabel('Show links between neighbours').check();
  await page.locator('.research-list button').first().click();await page.getByRole('button',{name:'Open original purchases',exact:true}).click();
  await expect(page.getByRole('table',{name:'Original pair purchases'}).locator('tbody tr')).toHaveCount(3);
  await page.getByRole('button',{name:'Show affected tokens'}).click();await expect(page.getByRole('table',{name:'Data issues'})).toContainText('MISSING_CREATION_SIGNATURE');
  await page.getByLabel('Prepared research example').selectOption(catalog.research[1].id);await expect(page.getByTestId('graph-counts')).toContainText('426 pairs');
  await page.getByRole('button',{name:'Original purchases for pair 0',exact:true}).click();await expect(page.getByRole('table',{name:'Original pair purchases'})).toBeVisible();
  await page.getByLabel('Prepared research example').selectOption(catalog.snapshot);await expect(page.getByRole('heading',{name:'Saved observations'})).toBeVisible();await expect(page.getByRole('table',{name:'Source observations'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Run analysis',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'Prepare snapshot',exact:true})).toHaveCount(0);
  expect(requests.every(request=>request.startsWith(baseURL!))).toBe(true);expect(requests.some(request=>new URL(request).pathname.includes('/api/'))).toBe(false);
  await expect(page.locator('html')).not.toHaveAttribute('data-csp-error');expect(errors).toEqual([]);
});

test('both real reference outcomes retain trade history, synthetic labels and offline lineage',async({page})=>{
  for(const run of catalog.runs){
    await page.goto(url(`/runs/${run.id}`));await page.reload();
    await expect(page.getByText('Test result · prepared offline',{exact:true})).toBeVisible();
    if(run.mode==='EXOGENOUS_VIRTUAL_SETTLEMENT')await expect(page.getByText('Synthetic execution model',{exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'Trades',exact:true}).click();
    await expect(page.getByRole('table',{name:'Entries and trades'}).locator('tbody tr')).toHaveCount(1);
    await page.getByRole('button',{name:/^Details /}).click();await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByRole('heading',{name:'Signal → decision → fill',exact:true})).toBeVisible();
    await expect(page.getByRole('dialog').locator('.recharts-surface').first()).toBeVisible();
    await page.keyboard.press('Escape');await page.getByRole('tab',{name:'Verification',exact:true}).click();
    await page.getByRole('link',{name:'Open manifest and lineage'}).click();await expect(page.getByRole('heading',{name:'Offline provenance'})).toBeVisible();await expect(page.locator('.react-flow__node').first()).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  }
});

test('unknown pages and unavailable execution never start an API request',async({page})=>{
  const requests:string[]=[];page.on('request',request=>requests.push(request.url()));
  await page.goto(url('/launch'));await expect(page.getByRole('heading',{name:'Unavailable in the demo'})).toBeVisible();
  await page.goto(url('/research?artifact='+'f'.repeat(64)));await expect(page.getByRole('alert')).toContainText('not included');
  expect(requests.some(request=>new URL(request).pathname.includes('/api/'))).toBe(false);
});

test('corrupt or missing static responses fail visibly and leave the demo banner',async({page})=>{
  const record=catalog.responses[`/api/v1/research/${catalog.research[0].id}`];
  const file=record.file;
  await page.route(`**/demo-data/${file}`,route=>route.fulfill({status:200,contentType:'application/json',body:'{}'}));
  await page.goto(url('/research'));await expect(page.getByRole('alert')).toContainText('does not match');await expect(page.getByText('Demo · test data',{exact:true})).toBeVisible();
  await page.unroute(`**/demo-data/${file}`);await page.route('**/demo-data/manifest.json',route=>route.fulfill({status:404,body:''}));await page.reload();await expect(page.getByRole('alert')).toContainText('unavailable');
});

});

function exported(route: string) {
  const parsed = new URL(route, 'https://demo.invalid'); parsed.searchParams.sort();
  const key = parsed.pathname + (parsed.searchParams.size ? '?' + parsed.searchParams.toString() : '');
  const record = catalog.responses[key];
  expect(record, `Exported route ${key}`).toBeTruthy();
  return { record, body: JSON.parse(readFileSync('demo-data/' + record.file, 'utf8')) };
}

test.describe('historical corpus', () => {
  test.skip(catalog.synthetic, 'The current distribution contains synthetic examples.');
  test('two-hour dataset metadata and static-only navigation remain usable on the project path', async ({ page, baseURL }) => {
    const requests: string[] = [], errors: string[] = [];
    page.on('request', request => requests.push(request.url())); page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => window.addEventListener('securitypolicyviolation', event => document.documentElement.setAttribute('data-csp-error', event.violatedDirective)));
    await page.goto(url('/dataset')); await page.reload();
    await expect(page.getByRole('heading', { name: 'Two hours of on-chain history' })).toBeVisible();
    await expect(page.getByText('Real history · simulated strategies', { exact: true })).toBeVisible();
    await expect(page.getByText('2 hours · 7,200 seconds', { exact: true })).toBeVisible();
    await expect(page.locator('time').first()).toHaveAttribute('datetime', catalog.source.start_utc);
    await expect(page.locator('time').last()).toHaveAttribute('datetime', catalog.source.end_utc);
    await expect(page.getByRole('link', { name: 'Explore backtest', exact: true })).toHaveCount(catalog.runs.length);
    await expect(page.getByRole('link', { name: 'On-chain research', exact: true })).toBeVisible();
    await page.screenshot({ path: 'demo-test-results/history-overview.png', fullPage: true });
    await page.getByRole('link', { name: 'Skip to content' }).focus(); await page.keyboard.press('Enter'); await expect(page.locator('#main')).toBeFocused();
    await page.getByText('Snapshot identities', { exact: true }).click();
    await page.getByRole('link', { name: catalog.source.snapshot_ids[0], exact: true }).click();
    await page.getByRole('button', { name: 'Lineage', exact: true }).click();
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    await page.goto(url('/missing-page')); await expect(page.getByRole('heading', { name: 'Unavailable on this static site' })).toBeVisible();
    expect(requests.every(request => request.startsWith(baseURL!))).toBe(true);
    expect(requests.some(request => new URL(request).pathname.includes('/api/'))).toBe(false);
    await expect(page.locator('html')).not.toHaveAttribute('data-csp-error'); expect(errors).toEqual([]);
  });

  if (!catalog.synthetic) for (const run of catalog.runs) test(`historical result ${run.title} retains all pages, trade detail and lineage`, async ({ page, baseURL }) => {
    test.setTimeout(120000);
    const requests: string[] = [], errors: string[] = [];
    page.on('request', request => requests.push(request.url())); page.on('pageerror', error => errors.push(error.message));
    const prefix = `/api/v1/run-artifacts/${run.id}`;
    let entryPage = exported(prefix + '/strategy-dashboard?limit=25').body.entries;
    const analytics = exported(prefix + '/analytics');
    await page.goto(url(`/runs/${run.id}`)); await page.reload();
    await expect(page.getByText('Historical backtest · prepared offline', { exact: true })).toBeVisible();
    await expect(page.getByText('Test result · prepared offline', { exact: true })).toHaveCount(0);
    if (run.mode === 'EXOGENOUS_VIRTUAL_SETTLEMENT') await expect(page.getByText('Synthetic execution model', { exact: true })).toBeVisible();
    for (const name of ['Entries', 'Exits']) {
      await page.getByRole('tab', { name, exact: true }).click();
      await expect(page.getByRole('heading', { name: name === 'Entries' ? 'Entry analytics' : 'Exit analytics', exact: true })).toBeVisible();
    }
    await page.getByRole('tab', { name: 'Trades', exact: true }).click();
    let count = 0, inspected = false;
    for (let pageNumber = 0; pageNumber < 400; pageNumber++) {
      const table = page.getByRole('table', { name: 'Entries and trades' });
      // The shared table renders a separate empty state for zero-entry runs.
      if (entryPage.items.length) {
        await expect(table.locator('tbody tr')).toHaveCount(entryPage.items.length);
        await expect(table.locator('tbody tr').first().locator('code')).toHaveText(entryPage.items[0].boundary_ordinal);
      }
      count += entryPage.items.length;
      const chartIndex = entryPage.items.findIndex((entry: { chart_availability: string }) => entry.chart_availability === 'AVAILABLE');
      if (!inspected && entryPage.items.length) {
        const index = chartIndex >= 0 ? chartIndex : 0, entry = entryPage.items[index];
        await page.getByRole('button', { name: /^Details / }).nth(index).click();
        const dialog = page.getByRole('dialog'); await expect(dialog).toBeVisible();
        await expect(dialog.getByRole('heading', { name: 'Signal → decision → fill', exact: true })).toBeVisible();
        if (entry.chart_availability === 'AVAILABLE') {
          const chart = exported(prefix + `/entries/${entry.entry_id}/chart?boundary_ordinal=${entry.boundary_ordinal}`);
          if ((chart.record.status ?? 200) === 200) await expect(dialog.locator('.recharts-surface').first()).toBeVisible();
          else await expect(dialog.getByRole('alert')).toContainText(chart.body.message);
        } else await expect(dialog.getByRole('heading', { name: 'Historical chart unavailable', exact: true })).toBeVisible();
        await page.keyboard.press('Escape'); inspected = true;
      }
      if (!entryPage.next_cursor) { await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled(); break; }
      const cursor = entryPage.next_cursor;
      entryPage = exported(prefix + `/entries?limit=25&after_target_boundary_ordinal=${cursor.target_boundary_ordinal}&after_roundtrip_id=${cursor.roundtrip_id}`).body;
      await page.getByRole('button', { name: 'Next page', exact: true }).click();
    }
    if ((analytics.record.status ?? 200) === 200) expect(BigInt(count)).toBe(BigInt(analytics.body.entry_count));
    await page.getByRole('tab', { name: 'Verification', exact: true }).click();
    await page.getByRole('link', { name: 'Open manifest and lineage', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Artifacts and lineage', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Lineage', exact: true }).click();
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(requests.every(request => request.startsWith(baseURL!))).toBe(true);
    expect(requests.some(request => new URL(request).pathname.includes('/api/'))).toBe(false); expect(errors).toEqual([]);
  });

  test('every product page opens and form previews remain interactive without execution', async ({ page, baseURL }) => {
    test.setTimeout(120000);
    const requests: { url: string; method: string }[] = [], errors: string[] = [];
    page.on('request', request => requests.push({ url: request.url(), method: request.method() }));
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('./');
    const navigation = [
      ['Overview', 'Work overview'], ['Strategy results', 'Strategy runs'],
      ['Launch strategy', 'Launch strategy'], ['Job queue', 'Job queue'],
      ['Prepare data', 'Prepare data'], ['Models and features', 'Models and features'],
      ['On-chain research', 'On-chain research'], ['Artifacts and lineage', 'Artifacts and lineage'],
      ['Resources', 'Resources and limits'], ['Published dataset', 'Two hours of on-chain history'],
    ];
    for (const [link, title] of navigation) {
      await page.locator('.sidebar').getByRole('link', { name: link, exact: true }).click();
      await expect(page.getByRole('heading', { name: title, level: 1, exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole('heading', { name: title, level: 1, exact: true })).toBeVisible();
      await expect(page.getByRole('alert')).toHaveCount(0);
      expect(await page.locator('body').innerText(), link).not.toMatch(/[\u0400-\u04ff]/);
      const slug = link.toLowerCase().replaceAll(' ', '-');
      await page.screenshot({ path: `demo-test-results/pages-${slug}-desktop.png`, fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), { message: `Mobile overflow on ${link}` }).toBe(true);
      await page.screenshot({ path: `demo-test-results/pages-${slug}-mobile.png`, fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1050 });
    }
    await page.goto(url('/launch'));
    for (const family of ['Pump.fun Sniping', 'Pump.fun Copy Buy', 'FirstSwap']) {
      const selector = page.getByRole('button', { name: new RegExp('^' + family.replace('.', '\\.')) });
      await selector.click(); await expect(selector).toHaveAttribute('aria-pressed', 'true');
      const input = page.locator('form input:visible').first();
      await expect(input).toBeEditable(); await input.fill('a'.repeat(64)); await expect(input).toHaveValue('a'.repeat(64));
      await expect(page.getByRole('button', { name: 'Run strategy', exact: true })).toBeDisabled();
      if (family === 'FirstSwap') await expect(page.getByRole('button', { name: 'Launch seed series', exact: true })).toBeDisabled();
      await expect(page.getByText('Form preview · execution disabled', { exact: true })).toBeVisible();
    }
    await page.goto(url('/data'));
    await expect(page.locator('form input:visible').first()).toBeEditable();
    for (const name of ['Inspect source', 'Build plan']) await expect(page.getByRole('button', { name, exact: true })).toBeDisabled();
    await page.goto(url('/ml'));
    for (const stage of ['Features', 'Universe', 'Labels', 'Training', 'Model schedule', 'Predictions']) {
      await page.getByRole('group', { name: 'ML stage', exact: true }).getByRole('button', { name: stage, exact: true }).click();
      await expect(page.getByRole('button', { name: 'Launch: ' + stage, exact: true })).toBeDisabled();
      await expect(page.locator('form input:visible').first()).toBeEditable();
    }
    await page.goto(url('/research'));
    await page.getByLabel('Window, seconds', { exact: true }).fill('120');
    await expect(page.getByLabel('Window, seconds', { exact: true })).toHaveValue('120');
    await page.getByRole('combobox', { name: /^Token mode/ }).selectOption('ALL');
    for (const name of ['Prepare snapshot', 'Run analysis']) await expect(page.getByRole('button', { name, exact: true })).toBeDisabled();
    await expect(page.getByRole('heading', { name: 'No wallet research results published', exact: true })).toBeVisible();
    await page.goto(url('/jobs')); await page.getByRole('combobox', { name: /^State/ }).selectOption('SUCCEEDED');
    await expect(page.getByRole('combobox', { name: /^State/ })).toHaveValue('SUCCEEDED');
    await expect(page.getByText('No execution host is connected. This preview has no live job queue.', { exact: true })).toBeVisible();
    await page.goto(url('/artifacts')); await page.getByLabel('Artifact ID', { exact: true }).fill(catalog.runs[0].id);
    await page.getByRole('button', { name: 'Open', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Metadata', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Lineage', exact: true }).click();
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    expect(requests.every(request => request.url.startsWith(baseURL!))).toBe(true);
    expect(requests.every(request => request.method === 'GET')).toBe(true);
    expect(requests.some(request => new URL(request.url).pathname.includes('/api/'))).toBe(false);
    expect(errors).toEqual([]);
  });

  test('historical corrupt files and unknown results fail visibly without API fallback', async ({ page }) => {
    const requests: string[] = []; page.on('request', request => requests.push(request.url()));
    await page.goto(url('/runs/' + 'f'.repeat(64))); await expect(page.getByRole('alert')).toContainText('not included');
    await page.route('**/demo-data/responses/*.json', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.goto(url('/runs/' + catalog.runs[0].id));
    await expect(page.getByRole('alert').first()).toContainText('does not match');
    await expect(page.getByText('Real history · simulated strategies', { exact: true })).toBeVisible();
    await page.route('**/demo-data/manifest.json', route => route.fulfill({ status: 404, body: '' })); await page.reload();
    await expect(page.getByRole('alert').first()).toContainText('unavailable');
    expect(requests.some(request => new URL(request).pathname.includes('/api/'))).toBe(false);
  });
});


test('published pages stay English despite saved Russian preferences and keep theme/mobile navigation', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('backtest.ui.language', 'ru'));
  await page.goto('./');
  await expect(page.getByRole('heading', { name: catalog.synthetic ? 'Explore the demo' : 'Work overview', exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByLabel('Language', { exact: true })).toHaveCount(0);
  await page.getByLabel('Appearance').selectOption('dark'); await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', { key: 'backtest.ui.language', newValue: 'ru' })));
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  expect(await page.locator('body').innerText()).not.toMatch(/[\u0400-\u04ff]/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open menu' }).click();
  await page.locator('.sidebar').getByRole('link', { name: catalog.synthetic ? 'On-chain research' : 'Strategy results', exact: true }).click();
  if (catalog.synthetic) await expect(page.getByTestId('graph-counts')).toBeVisible();
  else await expect(page.getByRole('link', { name: 'Explore backtest', exact: true })).toHaveCount(catalog.runs.length);
  await expect(page.locator('.sidebar')).not.toBeInViewport();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'demo-test-results/english-mobile.png', fullPage: true });
});
