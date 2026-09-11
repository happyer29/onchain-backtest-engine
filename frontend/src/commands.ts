import { t } from './i18n';
import { z } from 'zod';
import type { Json } from './api';
// Form values remain strings until the typed transport boundary.
export type Values = Record<string, string>;
export type Command = Record<string, Json>;
export const text = (values: Values, name: string) => z.string().trim().min(1, t("{0}: this field is required", [name])).parse(values[name]);
export const optional = (values: Values, name: string) => values[name]?.trim() || null;

export function integer(values: Values, name: string): bigint {
  const value = text(values, name);
  // Decimal syntax excludes floating point, signs, exponent notation, and silent rounding.
  if (!/^(0|[1-9][0-9]*)$/.test(value) || BigInt(value) > 18446744073709551615n) throw new Error(t("{0}: enter an integer from 0 to 18446744073709551615", [name]));
  return BigInt(value);
}
export const decimal = (values: Values, name: string) => integer(values, name).toString();
export const tokens = (values: Values, name: string) => [...new Set((values[name] ?? '').split(/[\s,]+/).filter(Boolean))].sort();
// Exact artifact lists are canonicalized before reaching the shared application resolver.
export function ids(values: Values, name: string) {
  return tokens(values, name).map(value => z.string().regex(/^[a-f0-9]{64}$/, t("{0}: a SHA-256 ID is required", [name])).parse(value));
}
const texts = (values: Values, names: string[]) => Object.fromEntries(names.map(name => [name, text(values, name)]));
const integers = (values: Values, names: string[]) => Object.fromEntries(names.map(name => [name, integer(values, name)]));

export function physical(values: Values): Command {
  // Operational settings live outside the semantic draft and use a closed backend set.
  const backend = z.enum(['reference-python-v1', 'numpy-mmap-first-swap-exact-v1', 'reference-pumpfun-sniping-v1', 'numpy-mmap-pumpfun-sniping-v1', 'reference-pumpfun-copy-buy-v1']).parse(values.run_backend);
  if (!['1', '2', '4'].includes(values.reader_readahead)) throw new Error(t("Readahead: choose 1, 2 or 4"));
  return { schema: 'backtest.run-physical-settings/v2', backend, ...integers(values, ['reader_batch_rows', 'reader_readahead', 'output_buffer_rows']), threads: integer(values, 'run_threads') };
}

export function firstSwapDraft(values: Values, seed?: bigint): Command {
  return { ...texts(values, ['snapshot_id', 'pool_id', 'sold_asset_id', 'bought_asset_id', 'execution_mode', 'inference_mode', 'inference_missing_policy']),
    ...integers(values, ['amount_in_atomic', 'minimum_amount_out_atomic', 'fee_bps', 'maximum_order_input_atomic', 'observation_slots', 'order_slots', 'inference_delay_boundaries']),
    // Optional exact dependencies retain explicit absence, with no latest/default resolution in UI.
    replay_pack_id: optional(values, 'replay_pack_id'), delivery_schedule_id: optional(values, 'delivery_schedule_id'),
    model_schedule_id: optional(values, 'model_schedule_id'), prediction_name: optional(values, 'prediction_name'),
    feature_set_ids: ids(values, 'feature_set_ids'), prediction_set_ids: ids(values, 'prediction_set_ids'),
    initial_portfolio: [{ asset_id: text(values, 'sold_asset_id'), amount_atomic: integer(values, 'initial_balance_atomic') }],
    // Root seed belongs to semantics; attempt nonce is allocated separately at submission.
    root_seed: seed ?? integer(values, 'root_seed'), maximum_dynamic_items: 1000000 };
}

function networkFees(values: Values, side: 'buy' | 'sell'): Command {
  return { profile_id: text(values, `${side}_fee_profile_id`), formula_version: text(values, `${side}_fee_formula_version`), transaction_format: text(values, `${side}_transaction_format`),
    effective_from_unix_s: integer(values, `${side}_fee_effective_from`), effective_until_unix_s: integer(values, `${side}_fee_effective_until`),
    // Atomic fee prices remain decimal strings under the existing Pump transport schema.
    charged_signature_count: integer(values, `${side}_signature_count`), lamports_per_signature: decimal(values, `${side}_lamports_per_signature`),
    compute_unit_limit: integer(values, `${side}_compute_unit_limit`), micro_lamports_per_compute_unit: decimal(values, `${side}_micro_lamports_per_cu`) };
}

export function pumpDraft(values: Values, family: 'sniping' | 'copy'): Command {
  const draft: Command = { contract_schema: family === 'copy' ? 'pumpfun-copy-buy-run-draft/v1' : 'pumpfun-sniping-run-draft/v3',
    ...texts(values, ['dataset_revision_id', 'snapshot_id', 'execution_mode']), replay_pack_id: optional(values, 'replay_pack_id'),
    ...integers(values, ['buy_slippage_bps', 'sell_slippage_bps', 'sell_delay_transactions']),
    // Balance, gross budget, and seed preserve their original exact decimal transport.
    ...Object.fromEntries(['initial_sol_balance_lamports', 'gross_buy_budget_lamports', 'root_seed'].map(name => [name, decimal(values, name)])),
    wallet_account_profile: { schema: 'pumpfun-solana-wallet-account-profile/v2', profile_id: text(values, 'wallet_profile_id'), initial_uva_state: text(values, 'wallet_mode'),
      effective_from_unix_s: integer(values, 'wallet_effective_from'), effective_until_unix_s: integer(values, 'wallet_effective_until'),
      // Wallet-scoped UVA and per-mint ATA deposits retain three distinct requirements.
      account_costs: [ ['pumpfun-user-volume-accumulator-v1', 'uva_rent_lamports'], ['solana-associated-token-account-legacy-v1', 'legacy_ata_rent_lamports'], ['solana-associated-token-account-token-2022-immutable-owner-v1', 'token_2022_ata_rent_lamports'] ].map(([requirement, field]) => ({ requirement_schema_id: requirement, deposit_lamports: decimal(values, field) })) },
    pump_fee_profile: { profile_id: text(values, 'pump_profile_id'), program_version: text(values, 'pump_program_version'),
      buy_formula_version: text(values, 'pump_buy_formula_version'), sell_formula_version: text(values, 'pump_sell_formula_version'),
      // Effective intervals and independently modeled fees are not inferred from a chart.
      effective_from_unix_s: integer(values, 'pump_effective_from'), effective_until_unix_s: integer(values, 'pump_effective_until'),
      protocol_fee_bps: integer(values, 'pump_protocol_fee_bps'), creator_fee_bps: integer(values, 'pump_creator_fee_bps') },
    buy_solana_fee_profile: networkFees(values, 'buy'), sell_solana_fee_profile: networkFees(values, 'sell') };
  if (family === 'sniping') return { ...draft, delivery_schedule_id: optional(values, 'delivery_schedule_id') };
  // Copy never borrows the Sniping schedule or changes its one-mint/four-attempt contract.
  return { ...draft, signing_wallets: text(values, 'signing_wallets').split(/\s+/), ...integers(values, ['take_profit_bps', 'stop_loss_bps', 'maximum_hold_seconds', 'observation_delay_transactions', 'buy_delay_transactions']) };
}

export function datasetPlan(values: Values): Command {
  return { ...texts(values, ['source_id', 'source_inspection_artifact_id', 'network_id', 'position_schema_id']),
    ...integers(values, ['from_block_ordinal', 'to_block_ordinal', 'warmup_blocks', 'settlement_tail_blocks', 'max_shard_blocks']), requested_days: null,
    requirements: [{ origin: 'STRATEGY', origin_id: 'local-ui-reference-strategy', capability_id: text(values, 'capability_id'), columns: tokens(values, 'columns') }],
    // Byte ceilings are exact conversions of integer GiB/MiB controls, not browser estimates.
    budget: { max_remote_bytes: integer(values, 'max_remote_gib') * 1024n ** 3n, max_local_bytes: integer(values, 'max_local_gib') * 1024n ** 3n,
      max_days: integer(values, 'max_days'), temporary_reserve_bytes: 1024 ** 3, disk_low_watermark_bytes: 1024 ** 3 },
    query: { max_execution_seconds: 900, max_memory_bytes: integer(values, 'query_memory_mib') * 1024n ** 2n, max_result_rows: 10000000 }, request_remote_estimate: false };
}

export type MlKind = 'features' | 'universe' | 'labels' | 'train' | 'schedule' | 'predict';
export const mlPaths: Record<MlKind, string> = { features: 'features', universe: 'universes', labels: 'labels', train: 'models/train', schedule: 'model-schedules', predict: 'predictions' };
export function mlCommand(kind: MlKind, values: Values, contract: Record<string, Json>): Command {
  const base = { spec_version: 1, compiler_version: contract.compiler_version };
  // Discovery supplies code/runtime identity; forms supply only typed data and causal controls.
  if (kind === 'features') return { ...base, ...texts(values, ['replay_pack_id', 'replay_semantics_id', 'replay_layout_schema_id']), input_feature_set_ids: [],
    feature_specs: [{ name: text(values, 'feature_name'), version: 1, entity_key: 'replay_row_id', input_ids: [], effective_time_semantics: 'replay-event-boundary-v1',
      available_time_semantics: 'event-boundary-plus-warmup-v1', warmup_boundaries: integer(values, 'warmup_boundaries'), dtype: '<i8',
      null_policy: values.feature_name === 'event_index' ? 'EXPLICIT_BITMAP' : 'FORBID', code_bundle_id: contract.feature_builder_bundle_id, runtime_lock_id: contract.runtime_lock_id }] };
  if (kind === 'universe') return { ...base, snapshot_id: text(values, 'snapshot_id'), universe_spec_id: contract.universe_spec_id, input_feature_set_ids: ids(values, 'feature_set_ids'), builder_bundle_id: contract.universe_builder_bundle_id, builder_config_digest: contract.universe_config_digest };
  // Labels stay in the training lifecycle; execution forms receive no label payload.
  if (kind === 'labels') return { ...base, ...texts(values, ['snapshot_id', 'universe_id']), label_spec_id: contract.label_spec_id, label_builder_bundle_id: contract.label_builder_bundle_id, label_config_digest: contract.label_config_digest, training_cutoff: integer(values, 'training_cutoff') };
  if (kind === 'train') return { ...base, training_spec: { feature_set_ids: ids(values, 'feature_set_ids'), ...texts(values, ['label_set_id', 'universe_id', 'hyperparameter_digest']),
    split: integers(values, ['train_from', 'train_until', 'validation_from', 'validation_until', 'purge_boundaries', 'embargo_boundaries']),
    root_seeds: tokens(values, 'root_seeds').map(root_seed => integer({ root_seed }, 'root_seed')), ...integers(values, ['training_cutoff', 'modeled_available_boundary']), trainer_bundle_id: contract.trainer_bundle_id, runtime_lock_id: contract.runtime_lock_id },
    // Exact framework and preprocessing/calibration identities survive submission unchanged.
    ...texts(values, ['feature_schema_digest', 'preprocessing_digest', 'calibration_digest']), ridge_lambda: integer(values, 'ridge_lambda'), framework: contract.trainer_framework, canonicality: 'CANONICAL_EXACT' };
  if (kind === 'schedule') return { ...base, schedule: { entries: [{ ...integers(values, ['eligible_from', 'eligible_until', 'training_cutoff', 'model_available_boundary']), model_bundle_id: text(values, 'model_bundle_id'), availability_basis: 'modeled-training-completion-v1' }], fallback_model_bundle_id: null }, canonicality: 'CANONICAL_EXACT' };
  return { ...base, ...texts(values, ['replay_pack_id', 'replay_semantics_id', 'replay_layout_schema_id', 'model_schedule_id', 'prediction_name', 'missing_policy']), feature_set_ids: ids(values, 'feature_set_ids'), model_bundle_ids: ids(values, 'model_bundle_ids'), inference_delay_boundaries: integer(values, 'inference_delay_boundaries'), canonicality: 'CANONICAL_EXACT' };
}
