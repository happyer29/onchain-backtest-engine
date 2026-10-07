import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { queryClient } from './api';
import { DatasetPreparation, Launch, useSubmission } from './forms';
import { ResearchForms } from './research/forms';
import { Artifacts, JobsPanel, Resources } from './workspace';
import { StaticPreviewProvider } from './preview';

const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/launch?strategy=firstswap']}><StaticPreviewProvider>{children}</StaticPreviewProvider></MemoryRouter></QueryClientProvider>;
afterEach(() => { queryClient.clear(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it('blocks submission before even preparing a resolver request in the static preview', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  const prepare = vi.fn(async () => ({ path: '/api/v1/backtests', body: {} }));
  const { result } = renderHook(() => useSubmission(), { wrapper });
  await act(async () => result.current.submit('preview-draft', prepare));
  expect(prepare).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  expect(result.current.receipt).toBeNull(); expect(result.current.busy).toBe(false);
});

it('keeps strategy and source controls editable while direct form submissions stay local', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  const launch = render(<Launch />, { wrapper });
  expect(screen.getByRole('button', { name: 'Run strategy' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Launch seed series' })).toBeDisabled();
  const input = launch.container.querySelector('input')!;
  expect(input).toBeEnabled(); fireEvent.change(input, { target: { value: 'a'.repeat(64) } });
  expect(input).toHaveValue('a'.repeat(64)); launch.unmount();
  const dataset = render(<DatasetPreparation />, { wrapper });
  expect(screen.getByRole('button', { name: 'Inspect source' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Build plan' })).toBeDisabled();
  const source = dataset.container.querySelector('input')!;
  fireEvent.change(source, { target: { value: 'published-source' } }); expect(source).toHaveValue('published-source');
  await act(async () => fireEvent.submit(source.closest('form')!));
  expect(fetch).not.toHaveBeenCalled();
});

it('allows research hypothesis edits without submitting either valid research form', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  render(<ResearchForms />, { wrapper });
  for (const [label, value] of [['From block, inclusive', '100'], ['To block, exclusive', '200'], ['Research snapshot ID', 'a'.repeat(64)], ['Window, seconds', '1000'], ['Token mode', 'ALL']]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  expect(screen.getByRole('button', { name: 'Prepare snapshot' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Run analysis' })).toBeDisabled();
  await act(async () => {
    fireEvent.submit(screen.getByRole('form', { name: 'Prepare research snapshot' }));
    fireEvent.submit(screen.getByRole('form', { name: 'Analyze wallets' }));
  });
  expect(screen.getByLabelText('Token mode')).toHaveValue('ALL');
  expect(screen.getByLabelText('Window, seconds')).toHaveValue(1000);
  expect(fetch).not.toHaveBeenCalled(); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('shows unavailable host resources and an explorable queue without polling or invented jobs', async () => {
  vi.useFakeTimers(); const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  render(<><Resources /><JobsPanel /></>, { wrapper });
  expect(screen.getByText(/This preview has no live job queue/)).toBeVisible();
  expect(screen.getAllByText('Unavailable in the published preview')).toHaveLength(4);
  fireEvent.change(screen.getByRole('combobox', { name: 'State' }), { target: { value: 'SUCCEEDED' } });
  expect(screen.getByRole('combobox', { name: 'State' })).toHaveValue('SUCCEEDED');
  expect(screen.getAllByRole('button', { name: 'Refresh' }).every(button => button.hasAttribute('disabled'))).toBe(true);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(fetch).not.toHaveBeenCalled(); expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
});

it('reads only public lineage descriptors for artifact metadata in preview', async () => {
  const id = 'a'.repeat(64), fetch = vi.fn(async (_url: string) => new Response(JSON.stringify({ root_artifact_id: id, artifacts: [{ artifact_id: id, kind: 'RUN_ARTIFACT', input_artifact_ids: [] }], edges: [] })));
  vi.stubGlobal('fetch', fetch);
  render(<Artifacts artifactId={id} />, { wrapper });
  await waitFor(() => expect(screen.getByText('Verified metadata')).toBeVisible());
  expect(fetch).toHaveBeenCalledTimes(1); expect(fetch.mock.calls[0][0]).toBe(`/api/v1/lineage/${id}`);
  expect(screen.getByRole('button', { name: 'Metadata' })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Manifest' })).not.toBeInTheDocument();
});
