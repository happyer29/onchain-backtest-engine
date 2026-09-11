import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { encode, queryClient, type Schema } from './api';
// Controlled transport ignores abort deliberately, reproducing queued late network completions.
import { EntryDetail, StrategyResults } from './results';
import { useSubmission } from './forms';
import { DataTable } from './table';
import { JobEvents } from './workspace';
import { chartFixture, entryFixture, runId, summaryFixture } from './test-fixtures';
import type { MarketChart } from './result-contracts';

vi.mock('./charts', () => ({ MarketHistoryChart: ({ chart }: { chart: MarketChart }) => <div data-testid="history">{chart.asset_id}</div>, DistributionChart: () => <div />, AmountChart: () => <div /> }));
type Pending = { url: string; signal: AbortSignal; init: RequestInit; respond: (value: unknown, status?: number) => void };
let pending: Pending[];
const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={queryClient}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>;
beforeEach(() => {
  pending = [];
  // Native browser focus/inert behavior is covered in Playwright; this DOM shim tracks modal state.
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => new Promise<Response>(resolve => pending.push({ url, init, signal: init.signal as AbortSignal, respond: (value, status = 200) => resolve(new Response(encode(value), { status })) }))));
});
afterEach(() => { queryClient.clear(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it('closing trade details aborts its request and ignores a late successful chart', async () => {
  const view = render(<EntryDetail runId={runId} entry={entryFixture()} onClose={() => view.unmount()} />, { wrapper });
  await waitFor(() => expect(pending).toHaveLength(1));
  fireEvent.click(screen.getByRole('button', { name: 'Close details' }));
  expect(pending[0].signal.aborted).toBe(true);
  // An ignored transport cancellation must still lose authority to commit chart state.
  await act(async () => pending[0].respond(chartFixture()));
  expect(screen.queryByTestId('history')).not.toBeInTheDocument();
  expect(document.querySelector('dialog')).toBeNull();
});
it('changing tokens cannot display the old token after its late response arrives', async () => {
  const first = entryFixture(), second = entryFixture('SECOND', '4'.repeat(64));
  const view = render(<EntryDetail key={first.entry_id} runId={runId} entry={first} onClose={() => {}} />, { wrapper });
  await waitFor(() => expect(pending).toHaveLength(1));
  view.rerender(<EntryDetail key={second.entry_id} runId={runId} entry={second} onClose={() => {}} />);
  // New identity owns an independent cache key and an independent cancellation signal.
  await waitFor(() => expect(pending).toHaveLength(2)); expect(pending[0].signal.aborted).toBe(true);
  await act(async () => pending[1].respond(chartFixture(second)));
  await waitFor(() => expect(screen.getByTestId('history')).toHaveTextContent('SECOND'));
  await act(async () => pending[0].respond(chartFixture(first)));
  expect(screen.getByTestId('history')).toHaveTextContent('SECOND');
});
it('invalid run navigation clears previous authority before showing validation failure', async () => {
  const view = render(<StrategyResults key={runId} runId={runId} />, { wrapper });
  await waitFor(() => expect(pending).toHaveLength(1));
  view.rerender(<StrategyResults key="invalid" runId="invalid" />);
  expect(pending[0].signal.aborted).toBe(true);
  // The late initial dashboard cannot seed the new route's summary or rows.
  await act(async () => pending[0].respond({ contract_schema: 'strategy-results/v1', summary: summaryFixture(), entries: { items: [entryFixture()], next_cursor: null } }));
  expect(screen.getByRole('alert')).toHaveTextContent('SHA-256');
  expect(queryClient.getQueryData(['strategy-summary', runId])).toBeUndefined();
});
it('optional scan failure leaves a separately verified scalar summary available', async () => {
  render(<StrategyResults runId={runId} />, { wrapper });
  await waitFor(() => expect(pending).toHaveLength(1));
  await act(async () => pending[0].respond({ code: 'RESULT_ANALYTICS_LIMIT_EXCEEDED', message: 'Scan limit' }, 422));
  await waitFor(() => expect(pending).toHaveLength(2));
  // Fallback reads only the existing summary; it never substitutes a partial entry page.
  expect(pending[1].url).toContain('/strategy-summary');
  await act(async () => pending[1].respond(summaryFixture()));
  await waitFor(() => expect(screen.getByText('Economic PnL')).toBeVisible());
  expect(screen.getByText('Scan limit')).toBeVisible();
  expect(screen.getByText('Full valuation unavailable')).toBeVisible();
});
it('one uncertain submission reuses its exact body, nonce and idempotency key', async () => {
  const { result } = renderHook(() => useSubmission());
  const prepare = vi.fn(async (attempt: { nonce: string }) => ({ path: '/api/v1/backtests', body: { attempt_nonce: attempt.nonce, amount: 9007199254740993001n } }));
  let first: Promise<void>;
  act(() => { first = result.current.submit('same-form', prepare); });
  await waitFor(() => expect(pending).toHaveLength(1));
  // A double click is rejected synchronously, before React's disabled state has rendered.
  await act(async () => result.current.submit('same-form', prepare)); expect(pending).toHaveLength(1);
  await act(async () => { pending[0].respond({ code: 'TEMPORARY', message: 'retry' }, 503); await first; });
  let retry: Promise<void>; act(() => { retry = result.current.submit('same-form', prepare); });
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(pending[1].init.body).toBe(pending[0].init.body); expect(pending[1].init.headers).toEqual(pending[0].init.headers);
  // The prepared immutable request is retained instead of resolving new physical inputs on retry.
  expect(prepare).toHaveBeenCalledTimes(1);
  await act(async () => { pending[1].respond({ job_id: 'job-fixture', job_type: 'RUN_BACKTEST' }); await retry; });
  expect(result.current.receipt?.job_id).toBe('job-fixture');
});
it('table defaults preserve server order and explicit sorting keeps nulls after exact wide values', () => {
  const rows = [{ id: 'null', money: null }, { id: 'larger', money: 9007199254740993n }, { id: 'smaller', money: 9007199254740992n }];
  render(<DataTable rows={rows} columns={[{ id: 'id', title: 'ID', render: row => row.id }, { id: 'money', title: 'PnL', value: row => row.money, render: row => String(row.money) }]} name="bounded" searchText={row => row.id} />);
  expect(screen.getAllByRole('row')[1]).toHaveTextContent('null');
  fireEvent.click(screen.getByRole('button', { name: 'PnL' }));
  // Adjacent integers above the Number safety limit must still have different sort ranks.
  expect(screen.getAllByRole('row')[1]).toHaveTextContent('larger'); expect(screen.getAllByRole('row')[3]).toHaveTextContent('null');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'smaller' } });
  expect(screen.getAllByRole('row')).toHaveLength(2); expect(screen.getByText('1 of 3 on this page')).toBeVisible();
});
it('job details observe terminal state independently of their stale list row and stop polling', async () => {
  const job = { job_id: 'job-fixture', job_type: 'RUN_BACKTEST', state: 'RUNNING' } as Schema<'JobResponse'>;
  render(<JobEvents job={job} onClose={() => {}} />, { wrapper });
  await waitFor(() => expect(pending).toHaveLength(1));
  await act(async () => pending[0].respond({ ...job, state: 'SUCCEEDED' }));
  // Reading events after state captures the durable terminal transition before polling stops.
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(pending[1].url).toContain('/events?after_event_id=0&limit=50');
  await act(async () => pending[1].respond({ items: [] }));
  await waitFor(() => expect(screen.getByText('SUCCEEDED')).toBeVisible());
  // A stale RUNNING selection cannot keep this completed job alive in the browser scheduler.
  vi.useFakeTimers();
  await act(async () => vi.advanceTimersByTimeAsync(6000));
  expect(pending).toHaveLength(2);
});
