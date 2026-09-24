import { z } from 'zod';
import { api, ApiError } from '../api';
import type { Row } from './types';

// The browser validates display envelopes; immutable recipe resolution remains application-owned.
const id = z.string().regex(/^[0-9a-f]{64}$/);
const decimal = z.string().regex(/^(0|[1-9][0-9]*)$/);
export const prepareSchema = z.object({ from_block: z.number().int().min(0).max(2 ** 32 - 1), to_block: z.number().int().min(1).max(2 ** 32) }).strict()
  .refine(value => value.to_block > value.from_block && value.to_block - value.from_block <= 300000, 'Choose an increasing range of at most 300,000 blocks.');
export const analysisSchema = z.object({ snapshot_id: id, window_seconds: z.number().int().min(0).max(3600), minimum_shared_mints: z.number().int().min(1).max(2000000), mode: z.enum(['NON_MAYHEM', 'ALL']), wallets: z.array(z.string().regex(/^[1-9A-HJ-NP-Za-km-z]{32,44}$/)).max(128) }).strict();
export type Analysis = z.infer<typeof analysisSchema>;
const summarySchema = z.object({ artifact_id: id, kind: z.enum(['RESEARCH_SNAPSHOT', 'RESEARCH_RESULT']),
  dataset: z.object({ schema: z.string(), network_id: z.string(), source_id: z.string(), from_block_ordinal: z.number().int().nonnegative(), to_block_ordinal: z.number().int().positive() }).passthrough(),
  counts: z.record(decimal), quality: z.record(z.unknown()), analysis: z.object({snapshot_id: id, window_seconds: z.number().int(), minimum_shared_mints: z.number().int(), wallets: z.array(z.string()), mode: z.enum(['NON_MAYHEM', 'ALL']).optional()}).passthrough().nullable(),
  mode_counts: z.record(decimal), data_issue_counts: z.record(decimal),
}).strict();
export type Summary = z.infer<typeof summarySchema>;
export type Table = 'observations' | 'token_modes' | 'data_issues' | 'activity' | 'pairs' | 'evidence';
const pageSchema = z.object({ artifact_id: id, table: z.string(), rows: z.array(z.record(z.string())).max(25), next_cursor: z.string().min(1).max(1024).nullable() }).strict();
export async function summary(id: string, signal: AbortSignal): Promise<Summary> {
  const result = summarySchema.parse(await api(`/api/v1/research/${id}`, { signal }));
  if (result.artifact_id !== id || (result.kind === 'RESEARCH_RESULT') !== (result.analysis !== null)) throw new Error('The research response belongs to another artifact.');
  return result;
}
export async function page(id: string, table: Table, cursor: string | null, pair: string | null, signal: AbortSignal): Promise<{rows: Row[]; next_cursor: string | null}> {
  const query = new URLSearchParams({limit: '25', ...(cursor ? {cursor} : {}), ...(pair !== null ? {pair} : {})});
  const result = pageSchema.parse(await api(`/api/v1/research/${id}/rows/${table}?${query}`, {signal}));
  if (result.artifact_id !== id || result.table !== table) throw new Error('The research response belongs to another artifact.');
  return result;
}
// Safe server codes offer recovery without exposing credentials, paths or raw library errors.
export function researchError(error: unknown): string {
  if (error instanceof ApiError && error.code === 'RESEARCH_REPREPARE_REQUIRED') return 'This snapshot has no token modes. Prepare a new snapshot for Without Mayhem, or use All modes.';
  if (error instanceof z.ZodError) return 'Check the research fields or response: exact IDs, integer bounds and at most 128 signer addresses are required.';
  return error instanceof Error ? error.message : 'Could not load research data.';
}
export const tableNames: Record<Table, string> = { observations: 'Source observations', token_modes: 'Token modes', data_issues: 'Data issues', activity: 'Signer activity', pairs: 'Wallet pairs', evidence: 'Original pair purchases' };
export const columns: Record<Table, string[]> = {
  observations: ['row_id','block_ordinal','transaction_index','signature','mint','side','signing_wallet','fee_payer','quote_amount_atomic'],
  token_modes: ['row_id','mint','mode','creation_ref','source_rows','issue'], data_issues: ['row_id','mint','issue','observation_rows'],
  activity: ['signing_wallet','buy_rows','sell_rows','mint_count','first_block','last_block','source_quote_buy_atomic','source_quote_sell_atomic'],
  pairs: ['row_id','signer_a','signer_b','shared_mints','a_first','b_first','same_transaction'],
  evidence: ['mint','delta_seconds','left_signature','right_signature','left_signing_wallet','right_signing_wallet','left_fee_payer','right_fee_payer','left_block_ordinal','right_block_ordinal'],
};
export const headings: Record<string, string> = {
  row_id: 'Row', block_ordinal: 'Block', transaction_index: 'Transaction index', signature: 'Transaction signature', mint: 'Token', side: 'Side', signing_wallet: 'Signer', fee_payer: 'Fee payer', quote_amount_atomic: 'SOL leg, lamports',
  mode: 'Token mode', creation_ref: 'Creation [block, transaction, instruction, signature]', source_rows: 'Creation records', issue: 'Data issue', observation_rows: 'Excluded observations',
  buy_rows: 'BUY rows', sell_rows: 'SELL rows', mint_count: 'Tokens', first_block: 'First block', last_block: 'Last block', source_quote_buy_atomic: 'BUY SOL legs, lamports', source_quote_sell_atomic: 'SELL SOL legs, lamports',
  signer_a: 'Signer A', signer_b: 'Signer B', shared_mints: 'Shared tokens', a_first: 'A earlier', b_first: 'B earlier', same_transaction: 'Same transaction', delta_seconds: 'Time B − A, seconds',
  left_signature: 'Transaction A', right_signature: 'Transaction B', left_signing_wallet: 'Signer A', right_signing_wallet: 'Signer B', left_fee_payer: 'Payer A', right_fee_payer: 'Payer B', left_block_ordinal: 'Block A', right_block_ordinal: 'Block B',
};
