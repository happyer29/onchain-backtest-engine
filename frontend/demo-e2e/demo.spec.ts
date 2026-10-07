import {readFileSync} from 'node:fs';
import {test,expect} from '@playwright/test';
const catalog=JSON.parse(readFileSync('demo-data/manifest.json','utf8'));
const url=(route:string)=>`./#${route}`;

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

test('Russian preferences persist and mobile navigation stays within the static site',async({page})=>{
  await page.goto('./');await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByLabel('Language').selectOption('ru');await page.getByLabel('Оформление').selectOption('dark');await page.reload();
  await expect(page.getByRole('heading',{name:'Изучите демо'})).toBeVisible();await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Открыть меню'}).click();await page.getByRole('link',{name:'Ончейн-исследования',exact:true}).click();await expect(page.getByTestId('graph-counts')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'demo-test-results/demo-mobile.png',fullPage:true});
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
    await page.goto('./'); await page.reload();
    await expect(page.getByRole('heading', { name: 'Two hours of on-chain history' })).toBeVisible();
    await expect(page.getByText('Real history · simulated strategies', { exact: true })).toBeVisible();
    await expect(page.getByText('2 hours · 7,200 seconds', { exact: true })).toBeVisible();
    await expect(page.locator('time').first()).toHaveAttribute('datetime', catalog.source.start_utc);
    await expect(page.locator('time').last()).toHaveAttribute('datetime', catalog.source.end_utc);
    await expect(page.getByRole('link', { name: 'Explore backtest', exact: true })).toHaveCount(catalog.runs.length);
    await expect(page.getByRole('link', { name: 'On-chain research', exact: true })).toHaveCount(0);
    await page.screenshot({ path: 'demo-test-results/history-overview.png', fullPage: true });
    await page.getByRole('link', { name: 'Skip to content' }).focus(); await page.keyboard.press('Enter'); await expect(page.locator('#main')).toBeFocused();
    await page.getByText('Snapshot identities', { exact: true }).click();
    await page.getByRole('link', { name: catalog.source.snapshot_ids[0], exact: true }).click();
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    await page.goto(url('/launch')); await expect(page.getByRole('heading', { name: 'Unavailable on this static site' })).toBeVisible();
    await page.goto(url('/research')); await expect(page.getByRole('heading', { name: 'Unavailable on this static site' })).toBeVisible();
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
    await expect(page.getByRole('heading', { name: 'Offline provenance', exact: true })).toBeVisible();
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(requests.every(request => request.startsWith(baseURL!))).toBe(true);
    expect(requests.some(request => new URL(request).pathname.includes('/api/'))).toBe(false); expect(errors).toEqual([]);
  });

  test('historical labels and preferences persist in Russian on mobile', async ({ page }) => {
    await page.goto('./'); await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await page.getByLabel('Language').selectOption('ru'); await page.getByLabel('Оформление').selectOption('dark'); await page.reload();
    await expect(page.getByRole('heading', { name: 'Два часа ончейн-истории' })).toBeVisible();
    await expect(page.getByText('Реальная история · симуляция стратегий', { exact: true })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Открыть меню' }).click();
    await page.locator('.sidebar').getByRole('link', { name: 'Результаты стратегии', exact: true }).click();
    await expect(page.getByRole('link', { name: 'Открыть бэктест', exact: true })).toHaveCount(catalog.runs.length);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: 'demo-test-results/history-mobile.png', fullPage: true });
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
