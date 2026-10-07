import {defineConfig} from '@playwright/test';
const port=process.env.BACKTEST_DEMO_TEST_PORT??'18745';
const prefix=process.env.BACKTEST_DEMO_BASE_PATH??'/onchain-backtest-engine/';
if(!['/onchain-backtest-engine/','/onchain-backtest-engine/copy-buy/'].includes(prefix))throw new Error('Unsupported static demo test path.');
export default defineConfig({
  testDir:'./demo-e2e',outputDir:'demo-test-results',workers:1,fullyParallel:false,timeout:30000,
  use:{baseURL:`http://127.0.0.1:${port}${prefix}`,viewport:{width:1440,height:1050},channel:process.env.BACKTEST_BROWSER_CHANNEL||undefined,trace:'retain-on-failure'},
  webServer:{command:'../.venv/bin/python scripts/serve-demo.py',env:{BACKTEST_DEMO_PORT:port,BACKTEST_DEMO_BASE_PATH:prefix},url:`http://127.0.0.1:${port}${prefix}`,reuseExistingServer:false,timeout:30000},
});
