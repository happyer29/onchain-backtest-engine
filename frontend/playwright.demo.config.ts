import {defineConfig} from '@playwright/test';
const port=process.env.BACKTEST_DEMO_TEST_PORT??'18745';
export default defineConfig({
  testDir:'./demo-e2e',outputDir:'demo-test-results',workers:1,fullyParallel:false,timeout:30000,
  use:{baseURL:`http://127.0.0.1:${port}/onchain-backtest-engine/`,viewport:{width:1440,height:1050},channel:process.env.BACKTEST_BROWSER_CHANNEL||undefined,trace:'retain-on-failure'},
  webServer:{command:'../.venv/bin/python scripts/serve-demo.py',env:{BACKTEST_DEMO_PORT:port},url:`http://127.0.0.1:${port}/onchain-backtest-engine/`,reuseExistingServer:false,timeout:30000},
});
