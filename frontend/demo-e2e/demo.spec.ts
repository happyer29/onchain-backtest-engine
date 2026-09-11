import {readFileSync} from 'node:fs';
import {test,expect} from '@playwright/test';
const catalog=JSON.parse(readFileSync('demo-data/manifest.json','utf8'));
const url=(route:string)=>`./#${route}`;

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
