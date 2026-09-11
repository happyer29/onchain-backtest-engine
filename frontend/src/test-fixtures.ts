import type { Entry, MarketChart, Summary, Analytics } from './result-contracts';
// Synthetic UI fixtures are confined to tests and never enter product routes or result storage.
export const runId = '1'.repeat(64);
export function entryFixture(asset = 'TOKEN', id = '2'.repeat(64)): Entry {
  return { entry_id: id, boundary_ordinal: '429496729602', signal_event_id: 'a'.repeat(64), asset_id: asset, quote_asset_id: 'SOL', actor_role: 'signing_wallet', actor_id: 'LEADER', status: 'CLOSED', exit_reason: 'STOP_LOSS',
    // Wide money and null economic valuation exercise separate formatting branches.
    realized_cash_pnl_atomic: '-9007199254740993001', economic_pnl_atomic: null, valuation_status: 'UNAVAILABLE', chart_availability: 'AVAILABLE', details: { execution_mode: 'EXOGENOUS_REPLAY', target_time_ns: '1700000000000000000' },
    attempts: [{ side: 'BUY', number: 0, status: 'FILLED', decision_boundary: '429496729602', landing_boundary: '429496729604', reference_out_atomic: '200', landing_out_atomic: '190', minimum_out_atomic: '180', failure_code: null }, { side: 'SELL', number: 1, status: 'FILLED', decision_boundary: '429496729609', landing_boundary: '429496729610', reference_out_atomic: '100', landing_out_atomic: '99', minimum_out_atomic: '90', failure_code: null }] };
}
export function point(tx: number, lifecycle: 'ACTIVE' | 'MIGRATED' = 'ACTIVE', cap = '9007199254740993001') {
  // Exact boundaries are fixture inputs to the client, whose renderer does not construct them.
  return { position: { network_id: 'solana:fixture', position_schema_id: 'block32-transaction32-v1', block_ordinal: 100, transaction_index: tx, event_index: null, boundary_ordinal: String((100n << 32n) + BigInt(tx) + 1n) }, block_time_ns: String(1700000000000000000n + BigInt(tx) * 1_000_000_000n), market_cap_atomic: cap, lifecycle };
}
export function chartFixture(entry = entryFixture()): MarketChart {
  return { contract_schema: 'strategy-market-cap/v1', market_cap_policy: 'post-transaction-total-supply-market-cap-lamports-floor/v1', run_artifact_id: runId, entry_id: entry.entry_id, snapshot_id: '3'.repeat(64), asset_id: entry.asset_id!, quote_asset_id: 'SOL',
    points: [point(0), point(1), point(8), point(10)], markers: [{ kind: 'SIGNAL', status: 'OBSERVED_SOURCE', attempt: null, failure_code: null, point: point(1) }, { kind: 'BUY', status: 'FILLED', attempt: 0, failure_code: null, point: point(3) }, { kind: 'SELL', status: 'FILLED', attempt: 1, failure_code: null, point: point(9) }] };
}
export function summaryFixture(family: Summary['family'] = 'PUMPFUN_COPY_BUY'): Summary {
  return { run_artifact_id: runId, logical_run_id: 'b'.repeat(64), family, network_id: 'solana:fixture', position_schema_id: 'block32-transaction32-v1', execution_mode: 'EXOGENOUS_VIRTUAL_SETTLEMENT', canonical_result_hash: 'c'.repeat(64), audit_hash: 'd'.repeat(64),
    // Monetary metrics retain original amounts and explicit availability in every family.
    metrics: [{ key: 'entry_count', value: '1', unit: 'count', availability: 'AVAILABLE' }, { key: 'closed_position_count', value: '1', unit: 'count', availability: 'AVAILABLE' }, { key: 'realized_cash_pnl_atomic', value: '-123456789', unit: 'atomic', availability: 'AVAILABLE' }, { key: 'economic_pnl_atomic', value: null, unit: 'atomic', availability: 'UNAVAILABLE' }, ...['protocol_fee_paid_atomic', 'creator_fee_paid_atomic', 'network_base_fee_paid_atomic', 'network_priority_fee_paid_atomic'].map((key, index) => ({ key, value: String(5000 * (index + 1)), unit: 'atomic' as const, availability: 'AVAILABLE' as const }))] };
}
export function analyticsFixture(): Analytics {
  return { contract_schema: 'strategy-analytics/v1', run_artifact_id: runId, entry_count: '1', distributions: [
    { key: 'entry_outcomes', population: 'entries', total: '1', items: [{ label: 'FILLED', count: '1' }] },
    { key: 'realized_pnl', population: 'valued_realized_entries', total: '1', items: [{ label: 'LOSS', count: '1' }] },
    // Attempt populations differ from entry count and remain labeled accordingly.
    { key: 'attempt_outcomes', population: 'attempts', total: '2', items: [{ label: 'BUY:FILLED', count: '1' }, { label: 'SELL:FILLED', count: '1' }] },
    { key: 'exit_reasons', population: 'entries_with_exit_decision', total: '1', items: [{ label: 'STOP_LOSS', count: '1' }] },
    { key: 'position_outcomes', population: 'entries', total: '1', items: [{ label: 'CLOSED', count: '1' }] },
    { key: 'failure_reasons', population: 'failed_or_rejected_attempts', total: '0', items: [] },
    { key: 'quote_slippage', population: 'attempts_with_both_quotes', total: '2', items: [{ label: 'ADVERSE', count: '2' }] },
  ] };
}
