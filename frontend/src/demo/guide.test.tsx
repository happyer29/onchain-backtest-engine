import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { setLocale } from '../i18n';
import { summaryFixture } from '../test-fixtures';
import type { Summary } from '../result-contracts';
import type { HistoricalCatalog, SyntheticCatalog } from './client';
import { CopyBuyGuide, ResultGuide, strictCopyRun } from './guide';

const wrapper = ({ children }: { children: React.ReactNode }) => <MemoryRouter>{children}</MemoryRouter>;
function run(id: string, family: Summary['family'], mode: HistoricalCatalog['runs'][number]['mode']) {
  return { id: id.repeat(64), title: 'An arbitrary public title', mode,
    summary: { ...summaryFixture(family), run_artifact_id: id.repeat(64), execution_mode: mode } };
}
function history(): HistoricalCatalog {
  return { schema: 'backtest.static-history/v1', recipe: 'indexer-two-hour-results/v1', synthetic: false, version: '0.2.0',
    source: { name: 'OnchainDivers', start_utc: '2026-09-01T00:00:00Z', end_utc: '2026-09-01T02:00:00Z', duration_seconds: 7200, from_block_ordinal: '1', to_block_ordinal: '2', snapshot_ids: ['a'.repeat(64)] },
    runs: [run('1', 'PUMPFUN_SNIPING', 'EXOGENOUS_REPLAY'), run('2', 'PUMPFUN_COPY_BUY', 'EXOGENOUS_VIRTUAL_SETTLEMENT'), run('3', 'PUMPFUN_COPY_BUY', 'EXOGENOUS_REPLAY')],
    response_bytes: 1, responses: {} };
}
function synthetic(): SyntheticCatalog {
  return { schema: 'backtest.static-demo/v1', recipe: 'synthetic-wallet-groups-and-copy-outcomes/v1', synthetic: true, wallets: 60, snapshot: 'a'.repeat(64),
    research: [{ id: 'b'.repeat(64), mode: 'NON_MAYHEM', counts: { pairs: '423' } }, { id: 'c'.repeat(64), mode: 'ALL', counts: { pairs: '426' } }],
    runs: history().runs.slice(1), response_bytes: 1, responses: {} };
}
afterEach(() => { act(() => { setLocale('en'); }); });

it('opens the verified strict Copy Buy identity, even when other families and virtual results precede it', () => {
  render(<CopyBuyGuide catalog={history()} />, { wrapper });
  expect(screen.getByRole('link', { name: 'Open strict replay result' })).toHaveAttribute('href', '/runs/' + '3'.repeat(64));
  expect(screen.getAllByRole('listitem')).toHaveLength(4);
  expect(screen.getByText(/not the saved configuration/)).toBeVisible();
  expect(screen.getAllByRole('link')).toHaveLength(2);
  expect(screen.queryByText(/sell attempts exhaust their limits/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('does not substitute another family or virtual execution when strict Copy Buy is absent', () => {
  const catalog = history(); catalog.runs.pop();
  render(<CopyBuyGuide catalog={catalog} />, { wrapper });
  expect(screen.queryByRole('link', { name: 'Open strict replay result' })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Open Copy Buy walkthrough (synthetic)' })).toHaveAttribute('href', './copy-buy/');
  expect(screen.getByText(/generated data is distinct from the historical dataset/)).toBeVisible();
  expect(screen.getAllByRole('link')).toHaveLength(2);
});

it('does not invent a result when the synthetic corpus lacks strict Copy Buy', () => {
  const catalog = synthetic(); catalog.runs.pop();
  render(<CopyBuyGuide catalog={catalog} />, { wrapper });
  expect(screen.getByRole('status')).toHaveTextContent('unavailable');
  expect(screen.queryByRole('link', { name: 'Open strict replay result' })).not.toBeInTheDocument();
});

it('rejects a summary with another result identity instead of routing by its title', () => {
  const catalog = history(); catalog.runs[0].summary = { ...summaryFixture(), execution_mode: 'EXOGENOUS_REPLAY', run_artifact_id: 'f'.repeat(64) };
  expect(() => strictCopyRun(catalog)).toThrow();
});

it('keeps synthetic failure expectations separate and provides Russian browser navigation', () => {
  act(() => { setLocale('ru'); });
  render(<CopyBuyGuide catalog={synthetic()} />, { wrapper });
  expect(screen.getByRole('link', { name: 'Открыть результат строгого replay' })).toHaveAttribute('href', '/runs/' + '3'.repeat(64));
  expect(screen.getByText(/попытки продажи исчерпываются/)).toBeVisible();
  expect(screen.getAllByRole('link')).toHaveLength(1);
  expect(screen.queryByRole('link', { name: 'Изучить настройки стратегии' })).not.toBeInTheDocument();
});

it('keeps real history guidance free of a fabricated fixed outcome', () => {
  render(<ResultGuide mode="EXOGENOUS_REPLAY" synthetic={false} />, { wrapper });
  expect(screen.getByText(/Historical market observations and modeled strategy trades/)).toBeVisible();
  expect(screen.queryByText(/failed sell attempts are intentional/)).not.toBeInTheDocument();
});
