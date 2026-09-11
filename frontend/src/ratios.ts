import { t } from './i18n';
import { percent } from './format';
import type { Summary } from './result-contracts';
// Ratios are display-only reductions of verified scalar metadata, with explicit denominators.
export function resultRatios(summary: Summary): { name: string; value: string; detail: string }[] {
  const values = Object.fromEntries(summary.metrics.map(metric => [metric.key, metric.value]));
  const count = (key: string) => values[key] == null ? null : BigInt(values[key]!);
  const ratio = (numerator: bigint | null, denominator: bigint | null) => numerator === null || denominator === null ? '—' : percent(numerator, denominator);
  const buys = count('accepted_buy_count') ?? count('filled_buy_count');
  // Closed buys and open valuation refer to distinct populations; neither is a win rate.
  const targets = count('target_count') ?? count('entry_count'), closed = count('closed_position_count');
  const open = count('open_position_count'), unvalued = count('unvalued_open_position_count');
  const feeParts = ['protocol_fee_paid_atomic', 'creator_fee_paid_atomic', 'network_base_fee_paid_atomic', 'network_priority_fee_paid_atomic'].map(count);
  const fees = feeParts.every(part => part !== null) ? feeParts as bigint[] : null;
  // A negative remainder or subset overflow throws through the normal result validation boundary.
  return [
    { name: t("Successful buys"), value: ratio(buys, targets), detail: t("Filled buys / signals") },
    { name: t("Position closure"), value: ratio(closed, buys), detail: t("Closed positions / buys") },
    { name: t("Valuation coverage"), value: ratio(open !== null && unvalued !== null ? open - unvalued : null, open), detail: t("Valued open / all open positions") },
    // Fee composition and synthetic funding are accounting shares, never profit attribution.
    { name: t("Venue fee share"), value: fees ? ratio(fees[0] + fees[1], fees.reduce((sum, fee) => sum + fee, 0n)) : '—', detail: t("Pump protocol + creator / all fees") },
    { name: t("Synthetic funding share"), value: ratio(count('synthetic_funded_sell_atomic'), count('gross_sell_settlement_atomic')), detail: t("Synthetic funding / gross sell proceeds") },
  ];
}
