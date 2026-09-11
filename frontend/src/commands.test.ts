import { describe, expect, it } from 'vitest';
import { decode, encode } from './api';
import { firstSwapDraft, integer, physical, pumpDraft, datasetPlan } from './commands';
import { formSchema, validateRunContract, type Field } from './forms';
import { atomic, axisAtomic, isoNanoseconds, percent } from './format';
// Real metadata supplies the same initial form state as the React launch screen.
import fields from './form-fields.json';
import type { Schema } from './api';
const values = (key: keyof typeof fields) => Object.fromEntries(fields[key].map(field => [field.name, field.default]));
const pump = () => ({ ...values('sniping-form'), dataset_revision_id: 'a'.repeat(64), snapshot_id: 'b'.repeat(64), execution_mode: 'EXOGENOUS_REPLAY', signing_wallets: 'WALLET' });

it('retains every wide integer digit across draft resolution and resubmission', () => {
  const raw = '{"resolved_spec":{"x":9007199254740993001,"negative":-9007199254740993001,"limit":200}}';
  expect(encode(decode(raw))).toBe(raw);
  expect(integer({ amount: '18446744073709551615' }, 'amount')).toBe(18446744073709551615n);
  expect(atomic('9007199254740993001', 9, 9)).toBe('9,007,199,254.740993001');
  // Missing valuation and denominator zero remain unavailable, never fabricated zero profit.
  expect(atomic(null)).toBe('—'); expect(percent('0', '0')).toBe('—'); expect(percent('1', '3')).toBe('33.33%');
  // Small fees stay nonzero, while wide chart ticks fit without losing exact tooltip values.
  expect(atomic('5000')).toBe('0.000005'); expect(axisAtomic(9007199254740993001n)).toBe('9.0 B');
});
it.each(['1e3', '-1', '01', '1.5', '18446744073709551616'])('rejects noncanonical unsigned integer %s', value => { expect(() => integer({ value }, 'value')).toThrow(); });
it('orders sub-millisecond timestamps and different timezone spellings exactly', () => {
  expect(isoNanoseconds('2026-01-01T00:00:00.000001Z')).toBeGreaterThan(isoNanoseconds('2026-01-01T00:00:00Z'));
  expect(isoNanoseconds('2026-01-01T03:00:00.12+03:00')).toBe(isoNanoseconds('2026-01-01T00:00:00.120000Z'));
});

describe('typed commands preserve existing family semantics', () => {
  it('keeps profiles exact and physical controls outside a Sniping draft', () => {
    const draft = pumpDraft(pump(), 'sniping');
    expect(draft.contract_schema).toBe('pumpfun-sniping-run-draft/v3');
    expect(draft.gross_buy_budget_lamports).toBe('100000000');
    // Fixed policy is resolver-owned and never written as an editable override.
    expect(draft).not.toHaveProperty('cooldown_seconds'); expect(draft).not.toHaveProperty('run_backend');
    expect(draft).toHaveProperty('wallet_account_profile.account_costs.2.deposit_lamports', '2074080');
    expect(physical(pump())).toMatchObject({ threads: 1n, reader_readahead: 1n });
  });
  it('omits Sniping schedules from Copy and retains its explicit signal and exit inputs', () => {
    const draft = pumpDraft({ ...pump(), delivery_schedule_id: 'c'.repeat(64) }, 'copy');
    expect(draft.contract_schema).toBe('pumpfun-copy-buy-run-draft/v1');
    expect(draft).not.toHaveProperty('delivery_schedule_id'); expect(draft.signing_wallets).toEqual(['WALLET']);
    expect(draft.take_profit_bps).toBe(2000n); expect(draft.buy_delay_transactions).toBe(500n);
  });
  it('uses lexical JSON numbers for FirstSwap and keeps the complete optional ML contract', () => {
    const draft = firstSwapDraft({ ...values('backtest-form'), snapshot_id: 'a'.repeat(64), pool_id: 'POOL', bought_asset_id: 'TOKEN', amount_in_atomic: '9007199254740993' });
    expect(draft.amount_in_atomic).toBe(9007199254740993n);
    expect(draft).toMatchObject({ feature_set_ids: [], model_schedule_id: null, prediction_set_ids: [], maximum_dynamic_items: 1000000 });
  });
  it('uses exact byte budgets and authoritative half-open block inputs in planning', () => {
    const plan = datasetPlan({ ...values('dataset-plan-form'), source_inspection_artifact_id: 'a'.repeat(64), capability_id: 'BLOCK_CLOCK', columns: 'b,a,a', from_block_ordinal: '100', to_block_ordinal: '110' });
    expect(plan).toHaveProperty('budget.max_remote_bytes', 20n * 1024n ** 3n);
    expect(plan).toHaveProperty('requirements.0.columns', ['a', 'b']); expect(plan.request_remote_estimate).toBe(false);
  });
});

it('fails discovery closed when fixed semantics, version or execution-mode vocabulary changes', () => {
  const contract: Schema<'RunContractListResponse'> = { items: [{ schema: 'pumpfun-sniping-run-draft/v3', title: 'Sniping', editable_fields: [{ name: 'execution_mode', kind: 'CLOSED_ENUM', required: true, enum_values: ['EXOGENOUS_REPLAY', 'EXOGENOUS_VIRTUAL_SETTLEMENT'] }], fixed_semantics: { buy_delay_transactions: '500', cooldown_seconds: '600', quote_asset: 'SOL', sell_all: 'true', sell_decision_delay_seconds: '2' } }] };
  expect(validateRunContract(contract, 'sniping')).toEqual(contract.items[0]);
  contract.items[0].fixed_semantics.cooldown_seconds = '599'; expect(() => validateRunContract(contract, 'sniping')).toThrow();
  // An unknown Copy version cannot silently use Sniping's admitted discovery response.
  expect(() => validateRunContract(contract, 'copy')).toThrow();
});
it('validates hidden advanced values with the same exact syntax and bounded fields', () => {
  const selected = fields['sniping-form'].filter(field => ['buy_slippage_bps', 'uva_rent_lamports'].includes(field.name)) as Field[];
  const schema = formSchema(selected);
  expect(schema.safeParse({ buy_slippage_bps: '10001', uva_rent_lamports: '1000' }).success).toBe(false);
  expect(schema.safeParse({ buy_slippage_bps: '500', uva_rent_lamports: '1e4' }).success).toBe(false);
});
