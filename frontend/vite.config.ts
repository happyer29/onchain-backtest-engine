import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Python serves prebuilt assets on the same origin; no production Node server is needed.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/static/',
  build: { outDir: '../src/backtest/interfaces/web/static', emptyOutDir: true, manifest: true },
  // Component tests use a local DOM and never connect to operational source data.
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], exclude: ['e2e/**', 'node_modules/**'] },
});
