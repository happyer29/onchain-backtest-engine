import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';
const fixture = () => JSON.parse(readFileSync('test-results/research-fixture.json','utf8')) as {snapshot:string;result:string};

test('research uses the shared shell, actual artifacts, all graph levels and exact evidence',async({page})=>{
  const {result}=fixture();const errors:string[]=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>window.addEventListener('securitypolicyviolation',event=>document.documentElement.setAttribute('data-csp-error',event.violatedDirective)));
  await page.goto(`/research?artifact=${result}`);
  await expect(page.getByRole('heading',{name:'On-chain research'})).toBeVisible();
  await expect(page.getByRole('link',{name:'Strategy results',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Relationships in this sample'})).toBeVisible();
  await expect(page.getByTestId('graph-counts')).toContainText('Current page');
  const initialCanvas=page.locator('.research-canvas');await initialCanvas.scrollIntoViewIfNeeded();const initialBox=(await initialCanvas.boundingBox())!;
  await initialCanvas.click({position:{x:initialBox.width/2,y:initialBox.height/2}});await expect(page.getByRole('heading',{name:'Pair 0',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Clear selection'}).click();
  await page.getByRole('combobox',{name:'Select wallet',exact:true}).selectOption({index:1});
  await expect(page.getByRole('heading',{name:'Incident pairs on this page · 1',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Clear selection'}).click();
  await expect(page.getByText('Token data is incomplete',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Show affected tokens'}).click();
  await expect(page.getByRole('table',{name:'Data issues'})).toContainText('MISSING_CREATION_SIGNATURE');
  await page.getByRole('button',{name:'Whole result',exact:true}).click();
  await expect(page.getByTestId('graph-counts')).toContainText('1 groups · 2 wallets');
  await expect(page.locator('.research-canvas canvas').first()).toBeVisible();
  await page.getByRole('button',{name:'Group 1 · 2 wallets · 1 internal pairs',exact:true}).click();
  await expect(page.getByTestId('graph-counts')).toContainText('all 1 internal pairs');
  await page.getByRole('button',{name:'All wallets in group'}).click();
  const wallet=await page.locator('.research-list button').first().textContent();
  await page.locator('.research-list button').first().click();
  await expect(page.getByTestId('graph-counts')).toContainText('All 1 incident pairs');
  await page.getByLabel('Show links between neighbours').check();
  await expect(page.getByTestId('graph-counts')).toContainText('shown');
  await page.getByRole('button',{name:'Expand graph'}).click();
  await expect(page.locator('.research-explorer')).toHaveClass(/expanded/);
  await page.getByRole('button',{name:'Fit graph'}).click();
  await page.getByRole('button',{name:'Reset layout'}).click();
  await page.locator('.research-list button').first().click();
  await page.getByRole('button',{name:'Open original purchases',exact:true}).click();
  await expect(page.getByRole('table',{name:'Original pair purchases'})).toContainText(wallet!);
  await expect(page.getByTestId('graph-counts')).toContainText('All 1 incident pairs');
  await page.getByRole('button',{name:'1 / All groups',exact:true}).click();
  await expect(page.getByTestId('graph-counts')).toContainText('1 groups · 2 wallets');
  await page.getByRole('button',{name:'Back to previous view'}).click();await expect(page.getByLabel('Show links between neighbours')).toBeChecked();await expect(page.getByTestId('graph-view-filter')).toContainText('restored');
  await page.getByRole('button',{name:'1 / All groups',exact:true}).click();await expect(page.getByTestId('graph-counts')).toContainText('1 groups · 2 wallets');
  await page.getByLabel('Language').selectOption('ru');
  await expect(page.getByRole('heading',{name:'Ончейн-исследования'})).toBeVisible();
  await page.getByLabel('Оформление').selectOption('dark');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.screenshot({path:'test-results/research-dark.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.locator('html')).not.toHaveAttribute('data-csp-error');expect(errors).toEqual([]);
});

test('real all-signer analysis queues, completes and opens verified output; prepare rejection is visible',async({page})=>{
  const {snapshot}=fixture();await page.goto(`/research?artifact=${snapshot}`);
  await expect(page.getByLabel('Research snapshot ID')).toHaveValue(snapshot);
  await page.getByLabel('Window, seconds').fill('180');
  await expect(page.getByLabel('Signers, optional')).toHaveValue('');
  await page.getByRole('button',{name:'Run analysis',exact:true}).click();
  await expect(page.locator('form[aria-label="Analyze wallets"] .research-receipt')).toContainText('SUCCEEDED',{timeout:30000});
  await page.locator('form[aria-label="Analyze wallets"]').getByRole('link',{name:'Open research output'}).click();
  await expect(page.getByRole('heading',{name:'Relationships in this sample'})).toBeVisible();
  await expect(page.getByText(/Committed analysis: window ≤ 180/)).toBeVisible();
  await page.getByRole('button',{name:'Prepare snapshot',exact:true}).click();
  await expect(page.locator('form[aria-label="Prepare research snapshot"] [role="alert"]')).toContainText('RESEARCH_SOURCE_NOT_CONFIGURED');
});

test('whole-result cancellation/retry, stale response and projection disposal follow React ownership',async({page})=>{
  const {result}=fixture();await page.goto(`/research?artifact=${result}`);await expect(page.getByTestId('graph-counts')).toBeVisible();
  let release:(()=>void)|undefined;let fullReads=0;
  await page.route(`**/api/v1/research/${result}/rows/pairs?limit=200`,async route=>{fullReads++;await new Promise<void>(resolve=>{release=resolve;});await route.continue().catch(()=>{});});
  await page.getByRole('button',{name:'Whole result',exact:true}).click();
  await expect.poll(()=>fullReads).toBe(1);await page.getByRole('button',{name:'Cancel graph loading'}).click();
  await expect(page.getByRole('alert')).toContainText('cancelled');
  release?.();await page.unroute(`**/api/v1/research/${result}/rows/pairs?limit=200`);
  await page.getByRole('button',{name:'Whole result',exact:true}).click();await expect(page.getByTestId('graph-counts')).toContainText('1 groups');
  await page.getByRole('button',{name:'Current page',exact:true}).click();await expect(page.getByTestId('graph-counts')).toContainText('Current page: all 1 pairs');
  await page.getByRole('link',{name:'Strategy results',exact:true}).click();await expect(page.locator('.research-canvas')).toHaveCount(0);
});

test('display threshold hides exact pairs without changing groups or evidence, and navigation restores zoom',async({page})=>{
  const {result}=fixture();const requests:string[]=[];page.on('request',r=>{if(r.url().includes('/rows/pairs'))requests.push(r.url());});
  await page.goto(`/research?artifact=${result}`);await expect(page.getByTestId('graph-counts')).toBeVisible();
  await page.getByRole('button',{name:'Whole result',exact:true}).click();await expect(page.getByTestId('graph-counts')).toContainText('1 groups · 2 wallets');
  await page.getByRole('button',{name:'Zoom in graph',exact:true}).click();await expect(page.getByTestId('graph-zoom')).toHaveText('125%');
  await page.getByRole('button',{name:'Group 1 · 2 wallets · 1 internal pairs',exact:true}).click();await expect(page.getByRole('button',{name:'All wallets in group'})).toBeVisible();
  await page.getByRole('button',{name:'Back to previous view'}).click();await expect(page.getByTestId('graph-counts')).toContainText('1 groups');await expect(page.getByTestId('graph-zoom')).toHaveText('125%');await expect(page.getByTestId('graph-view-filter')).toContainText('restored');
  const count=requests.length;
  await page.getByLabel('Show pairs with at least this many shared tokens').fill('3');await page.getByRole('button',{name:'Apply display filter'}).click();
  await expect(page.getByTestId('graph-filter-counts')).toContainText('0 shown + 1 hidden = 1 pairs');await expect(page.getByTestId('graph-counts')).toContainText('1 groups · 2 wallets');
  await expect(page.getByRole('button',{name:'Group 1 · 2 wallets · 0 internal pairs',exact:true})).toBeVisible();
  await page.getByRole('combobox',{name:'Select wallet',exact:true}).selectOption({index:1});await expect(page.getByTestId('graph-counts')).toContainText('All 1 incident pairs');await expect(page.getByTestId('graph-view-filter')).toContainText('0 shown + 1 hidden');
  await page.getByRole('button',{name:'Show every pair'}).click();await expect(page.getByTestId('graph-filter-counts')).toContainText('1 shown + 0 hidden');expect(requests.length).toBe(count);
  await page.locator('.research-list button').first().click();await page.getByRole('button',{name:'Open original purchases',exact:true}).click();await expect(page.getByRole('table',{name:'Original pair purchases'})).toBeVisible();
});

test('worker cancellation and worker failure leave retry and exact tables available',async({page})=>{
  const {result}=fixture();let release:(()=>void)|undefined;
  await page.route('**/layout.worker-*.js',async route=>{await new Promise<void>(resolve=>release=resolve);await route.continue().catch(()=>{});});
  await page.goto(`/research?artifact=${result}`);await expect(page.getByRole('button',{name:'Cancel view construction'})).toBeVisible();
  await expect.poll(()=>Boolean(release)).toBe(true);await page.getByRole('button',{name:'Cancel view construction'}).click();await expect(page.locator('.research-explorer [role="alert"]')).toContainText('cancelled');
  release?.();await page.unroute('**/layout.worker-*.js');
  await page.route('**/layout.worker-*.js',route=>route.fulfill({contentType:'application/javascript',body:'throw new Error("worker fixture");'}));
  await page.locator('.research-explorer').getByRole('button',{name:'Retry',exact:true}).click();await expect(page.locator('.research-explorer [role="alert"]')).toContainText('worker failed');
  await expect(page.getByRole('table',{name:'Wallet pairs'})).toBeVisible();await page.unroute('**/layout.worker-*.js');
  await page.locator('.research-explorer').getByRole('button',{name:'Retry',exact:true}).click();await expect(page.getByTestId('graph-counts')).toContainText('Current page');
});

test('WebGL unavailable is an explicit graph failure with usable purchase evidence',async({page})=>{
  const {result}=fixture();await page.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;Object.defineProperty(HTMLCanvasElement.prototype,'getContext',{value:function(this:HTMLCanvasElement,type:string,...rest:unknown[]){if(type==='webgl'||type==='webgl2'||type==='experimental-webgl')return null;return Reflect.apply(original,this,[type,...rest]);}});});
  await page.goto(`/research?artifact=${result}`);await expect(page.locator('.research-explorer [role="alert"]')).toContainText('WebGL graph rendering is unavailable');await expect(page.getByRole('table',{name:'Wallet pairs'})).toBeVisible();
  await page.getByRole('button',{name:'Original purchases for pair 0'}).click();await expect(page.getByRole('table',{name:'Original pair purchases'})).toBeVisible();
});

test('a context-loss event releases Sigma and permits a fresh view without changing the result',async({page})=>{
  const {result}=fixture();await page.goto(`/research?artifact=${result}`);await expect(page.getByTestId('graph-counts')).toBeVisible();
  await page.locator('.research-sigma canvas').first().evaluate(canvas=>canvas.dispatchEvent(new Event('webglcontextlost',{cancelable:true})));
  await expect(page.locator('.research-explorer [role="alert"]')).toContainText('WebGL context was lost');await expect(page.locator('.research-sigma')).toHaveCount(0);await expect(page.getByRole('table',{name:'Wallet pairs'})).toBeVisible();
  await page.locator('.research-explorer').getByRole('button',{name:'Retry',exact:true}).click();await expect(page.getByTestId('graph-counts')).toBeVisible();
});

test('dragged node positions survive leaving and returning to the same graph view',async({page})=>{
  const {result}=fixture();await page.emulateMedia({reducedMotion:'reduce'});await page.goto(`/research?artifact=${result}`);await expect(page.getByTestId('graph-counts')).toBeVisible();
  await page.getByRole('button',{name:'Whole result',exact:true}).click();await expect(page.getByTestId('graph-counts')).toContainText('1 groups');
  const canvas=page.locator('.research-canvas');await canvas.scrollIntoViewIfNeeded();const box=(await canvas.boundingBox())!;
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+80,box.y+box.height/2-45,{steps:12});await page.mouse.up();await page.mouse.move(5,5);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));const before=await canvas.screenshot({animations:'disabled'});
  await page.getByRole('button',{name:'Group 1 · 2 wallets · 1 internal pairs',exact:true}).click();await expect(page.getByTestId('graph-counts')).toContainText('all 1 internal pairs');
  await page.getByRole('button',{name:'Back to previous view'}).click();await expect(page.getByTestId('graph-view-filter')).toContainText('restored');await page.mouse.move(5,5);
  const after=await canvas.screenshot({animations:'disabled'});expect(after.equals(before)).toBe(true);
});
