import { test, expect } from '@playwright/test';
import { analyticsFixture, chartFixture, entryFixture, runId, summaryFixture } from '../src/test-fixtures';
// Real-server tests cover security/packaging; isolated route fixtures cover adversarial result timing.
test('real published FirstSwap result, shared UI, exact details and lineage', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => { window.addEventListener('securitypolicyviolation', event => { document.documentElement.setAttribute('data-csp-error', event.violatedDirective); }); });
  await page.goto('/');
  // The result list comes from actual publication and the production verified Run index.
  await expect(page.getByRole('heading', { name: 'Work overview' })).toBeVisible();
  await page.screenshot({ path: 'test-results/overview.png', fullPage: true });
  await page.getByRole('link', { name: 'Results', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Strategy results' })).toBeVisible();
  await expect(page.getByText('Not applicable to this strategy').first()).toBeVisible();
  await page.getByRole('tab', { name: 'Trades', exact: true }).click();
  // FirstSwap exposes its actual stored fill while keeping PnL explicitly nonapplicable.
  await expect(page.getByRole('table', { name: 'Entries and trades' })).toContainText('FILLED');
  await page.getByRole('button', { name: /^Details / }).first().click();
  await expect(page.locator('dialog')).toBeVisible();
  await expect(page.getByText('Historical chart unavailable')).toBeVisible();
  await page.locator('dialog summary').filter({ hasText: /^fills/ }).click();
  await page.getByRole('button', { name: 'Close details' }).click();
  // The underlying selected tab and list survive the modal lifecycle.
  await expect(page.getByRole('tab', { name: 'Trades', exact: true })).toHaveAttribute('data-state', 'active');
  await page.getByRole('tab', { name: 'Verification', exact: true }).click();
  await page.getByRole('link', { name: 'Open manifest and lineage' }).click();
  await page.getByRole('button', { name: 'Lineage', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Lineage graph' })).toBeVisible();
  // The graph must load under the original script/style CSP, without broadening it.
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  await expect(page.locator('html')).not.toHaveAttribute('data-csp-error');
  expect(errors).toEqual([]);
});

test('single-page launch controls, dark persistence and mobile navigation', async ({ page }) => {
  await page.goto('/launch?strategy=copy');
  await expect(page.getByText('Contract ready', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/launch-strategy.png', fullPage: true });
  await expect(page.getByLabel('signing_wallet', { exact: false })).toBeVisible();
  await expect(page.getByLabel('DeliverySchedule ID', { exact: false })).toHaveCount(0);
  // Advanced settings stay in the same route and synthetic mode has a persistent explanation.
  await page.getByLabel('Execution mode').selectOption('EXOGENOUS_VIRTUAL_SETTLEMENT');
  await expect(page.getByText(/Synthetic mode:/)).toBeVisible();
  await page.getByRole('button', { name: /Execution resources/ }).click();
  await expect(page.getByLabel('Run backend', { exact: true })).toHaveValue('reference-pumpfun-copy-buy-v1');
  await page.getByLabel('Appearance').selectOption('dark'); await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  // Small screens expose the same navigation without horizontal page overflow.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open menu' }).click();
  await page.getByRole('link', { name: 'Strategy results', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Strategy runs' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/mobile-dark.png', fullPage: true });
});

test('shared Pump charts render under CSP and preserve the page beneath trade details', async ({ page }) => {
  const errors: string[] = [], requests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const entry = entryFixture(), summary = summaryFixture();
  await page.route(`**/api/v1/run-artifacts/${runId}/**`, async route => {
    const path = new URL(route.request().url()).pathname; requests.push(path);
    // These are explicit synthetic transport fixtures, never published successful-run artifacts.
    if (path.endsWith('/strategy-dashboard')) return route.fulfill({ json: { contract_schema: 'strategy-results/v1', summary, entries: { items: [entry], next_cursor: null } } });
    if (path.endsWith('/analytics')) return route.fulfill({ json: analyticsFixture() });
    if (path.endsWith('/chart')) return route.fulfill({ json: chartFixture(entry) });
    throw new Error(`Unexpected request ${path}`);
  });
  await page.addInitScript(() => { window.addEventListener('securitypolicyviolation', event => { document.documentElement.setAttribute('data-csp-error', event.violatedDirective); }); });
  await page.goto(`/runs/${runId}`);
  // Recharts renders only bounded normalized geometry with exact accessible legends.
  await expect(page.locator('.recharts-sector').first()).toBeVisible();
  await page.screenshot({ path: 'test-results/results-warm.png', fullPage: true });
  await page.getByRole('tab', { name: 'Trades', exact: true }).click();
  await page.getByRole('button', { name: /^Details / }).click();
  await expect(page.locator('dialog .market-chart')).toBeVisible();
  await expect(page.locator('dialog .recharts-line-curve')).toHaveAttribute('d', /^M.+L/);
  await expect(page.locator('dialog')).toContainText('Synthetic mode:');
  // Local zoom reuses the same bounded history and exposes its selected mode accessibly.
  await page.getByRole('button', { name: 'Full history', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Full history', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: 'test-results/trade-detail.png', fullPage: true });
  // Both summary analytics and history are one-shot immutable reads, independent of focus.
  await page.getByRole('button', { name: 'Close details' }).click();
  await expect(page.locator('dialog')).toHaveCount(0);
  expect(requests.filter(path => path.endsWith('/analytics'))).toHaveLength(1);
  expect(requests.filter(path => path.endsWith('/chart'))).toHaveLength(1);
  await expect(page.locator('html')).not.toHaveAttribute('data-csp-error'); expect(errors).toEqual([]);
});

test('React resolves and submits a typed FirstSwap run to a real isolated child', async ({ page }) => {
  await page.goto('/launch?strategy=firstswap');
  const runs = await (await page.request.get('/api/v1/runs?limit=1')).json();
  const artifact = await (await page.request.get(`/api/v1/artifacts/${runs.items[0].run_artifact_id}`)).json();
  // Only the published snapshot ID is read from metadata; the form sends its own typed draft.
  const snapshot = artifact.manifest.resolved_run_spec.snapshot_id;
  await expect(page.getByText('Contract ready', { exact: true })).toBeVisible();
  const values: Record<string, string> = { snapshot_id: snapshot, pool_id: 'pool', bought_asset_id: 'TOKEN', amount_in_atomic: '100', minimum_amount_out_atomic: '0', maximum_order_input_atomic: '1000', initial_balance_atomic: '1000', observation_slots: '0', order_slots: '0' };
  for (const [name, value] of Object.entries(values)) await page.locator(`[name="${name}"]`).fill(value);
  // Capture the real resolve and durable submit responses, with no route interception.
  const resolution = page.waitForResponse(response => response.url().endsWith('/api/v1/run-specs/resolve'));
  const submission = page.waitForResponse(response => response.url().endsWith('/api/v1/backtests'));
  await page.getByRole('button', { name: 'Run strategy', exact: true }).click();
  expect((await resolution).status()).toBe(200);
  const response = await submission; expect(response.ok()).toBe(true);
  // Read the receipt consumed by React; Chromium may discard the DevTools response body.
  const receipt = page.getByRole('status').filter({ hasText: 'Job queued' });
  await expect(receipt).toBeVisible();
  const jobId = await receipt.locator('code').innerText();
  expect(jobId).not.toBe('');
  // Verify the exact displayed job reaches publication and has real supervisor progress.
  await expect.poll(async () => (await page.request.get(`/api/v1/jobs/${jobId}`)).json(), { timeout: 20_000 }).toMatchObject({ job_id: jobId, state: 'SUCCEEDED' });
  const events = await (await page.request.get(`/api/v1/jobs/${jobId}/events?limit=50`)).json();
  expect(events.items.some((event: { event_type: string }) => event.event_type === 'ATTEMPT_PROGRESS')).toBe(true);
  // Queue navigation follows the visible receipt only after the submitted job is verified.
  await page.getByRole('link', { name: 'Open queue' }).click();
  await expect(page.getByRole('heading', { name: 'Job queue' })).toBeVisible();
});

// Locale is independent of browser defaults, transport identity and the current form draft.
test('English default, persistent Russian choice and cross-tab synchronization', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ locale: 'ru-RU', baseURL });
  const page = await context.newPage();
  await page.goto('/launch?strategy=copy');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  // Changing presentation must preserve exact field values without submitting a command.
  await expect(page.getByText('Contract ready', { exact: true })).toBeVisible();
  await page.locator('[name="gross_buy_budget_lamports"]').fill('123456789');
  await page.getByLabel('Language', { exact: true }).selectOption('ru');
  await expect(page.getByRole('heading', { name: 'Запуск стратегии' })).toBeVisible();
  await expect(page.locator('[name="gross_buy_budget_lamports"]')).toHaveValue('123456789');
  // A new tab uses the stored choice; switching either tab updates the other in place.
  const second = await context.newPage();
  await second.goto('/');
  await expect(second.locator('html')).toHaveAttribute('lang', 'ru');
  await second.getByLabel('Язык', { exact: true }).selectOption('en');
  await expect(page.getByRole('heading', { name: 'Launch strategy' })).toBeVisible();
  await expect(page.locator('[name="gross_buy_budget_lamports"]')).toHaveValue('123456789');
  // Persistence survives reload without relying on navigator.language.
  await second.reload();
  await expect(second.locator('html')).toHaveAttribute('lang', 'en');
  await context.close();
});

// User-facing text across every route is English until an explicit language choice.
test('all workspace routes use English by default', async ({ page }) => {
  for (const route of ['/', '/runs', '/launch?strategy=sniping', '/data', '/ml', '/resources', '/artifacts', '/jobs']) {
    await page.goto(route);
    await expect(page.locator('h1')).toBeVisible();
    // The optional language's native name stays recognizable in the selector.
    const text = await page.locator('body').innerText();
    expect(text.replaceAll('Русский', '')).not.toMatch(/[А-Яа-яЁё]/);
  }
});
