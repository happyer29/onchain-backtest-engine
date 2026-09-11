import { t, localeTag, decimalSeparator } from './i18n';
// Display arithmetic never promotes an atomic amount or chain coordinate to Number.
export function decimal(value: string | bigint | number | null | undefined): bigint | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' && !Number.isSafeInteger(value)) throw new Error(t("Imprecise integer value."));
  if (!/^-?(?:0|[1-9]\d*)$/.test(String(value))) throw new Error(t("Invalid integer."));
  return BigInt(value);
}

export function atomic(value: string | bigint | null | undefined, decimals = 9, places = 4): string {
  const amount = decimal(value);
  if (amount === null) return '—';
  const magnitude = amount < 0n ? -amount : amount;
  // Truncation is presentation only; the original exact amount remains available in tooltips.
  const power = 10n ** BigInt(decimals);
  const fullFraction = (magnitude % power).toString().padStart(decimals, '0');
  // Small nonzero fees must not display as zero merely because the default precision is four.
  const fraction = magnitude > 0n && magnitude < power && /^0*$/.test(fullFraction.slice(0, places)) ? fullFraction.replace(/0+$/, '') : fullFraction.slice(0, places);
  return `${amount < 0n ? '−' : ''}${(magnitude / power).toLocaleString(localeTag())}${fraction ? decimalSeparator() + fraction : ''}`;
}

export function percent(numerator: string | bigint, denominator: string | bigint): string {
  const n = BigInt(numerator), d = BigInt(denominator);
  if (n < 0n || d < 0n || n > d) throw new Error(t("Ratios do not reconcile with totals."));
  if (d === 0n) return '—';
  // Half-up rounding to two percentage decimals matches the existing summary contract.
  const scaled = (n * 10_000n + d / 2n) / d;
  return `${scaled / 100n}${decimalSeparator()}${(scaled % 100n).toString().padStart(2, '0')}%`;
}

export function axisAtomic(amount: bigint): string {
  // Compact labels fit chart axes; exact original lamports remain in tooltips and the raw table.
  const magnitude = amount < 0n ? -amount : amount;
  for (const [power, suffix] of [[18, t("B")], [15, t("M")], [12, t("K")]] as const) {
    if (magnitude >= 10n ** BigInt(power)) return `${atomic(amount, power, 1)} ${suffix}`;
  }
  return atomic(amount, 9, 1);
}

export const shortId = (id: string, length = 8) => `${id.slice(0, length)}…${id.slice(-4)}`;
export const dateTime = (value: string) => new Date(value).toLocaleString(localeTag(), { dateStyle: 'short', timeStyle: 'short' });
export function isoNanoseconds(value: string): bigint {
  const match = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)$/.exec(value);
  if (!match) throw new Error(t("Invalid result timestamp."));
  // Normalize the timezone at whole seconds, then retain the exact fractional ordering.
  const seconds = Date.parse(match[1] + match[3]);
  if (!Number.isFinite(seconds)) throw new Error(t("Invalid result timestamp."));
  return BigInt(seconds) * 1_000_000n + BigInt((match[2] ?? '').padEnd(9, '0'));
}
export function nanosecondTime(value: string | number | bigint): string {
  // Converting only bounded epoch milliseconds avoids precision loss in the original timestamp.
  const ms = BigInt(value) / 1_000_000n;
  return dateTime(new Date(Number(ms)).toISOString());
}

export const labels: Record<string, string> = {
  entry_count: "Signals / entries", realized_cash_pnl_atomic: "Realized PnL",
  economic_pnl_atomic: "Economic PnL", valued_economic_pnl_subtotal_atomic: "Valued PnL subtotal",
  closed_position_count: "Closed positions", open_position_count: "Open positions",
  // Order outcomes are separate from position and valuation state.
  accepted_order_count: "Accepted orders", rejected_order_count: "Pre-submit rejections",
  filled_order_count: "Filled orders", failed_order_count: "Execution failures",
  accepted_buy_count: "Successful buys", filled_buy_count: "Successful buys",
  cooldown_skipped_count: "Skipped by cooldown", failed_buy_count: "Buy failures",
  // Fees, refundable deposits and cashback preserve distinct accounting meanings.
  protocol_fee_paid_atomic: "Protocol fee", creator_fee_paid_atomic: "Creator fee",
  network_base_fee_paid_atomic: "Base network fee", network_priority_fee_paid_atomic: 'Priority fee',
  account_deposit_paid_atomic: "Account deposits paid", account_deposit_refunded_atomic: "Account deposits refunded",
  account_deposit_locked_atomic: "Account deposits locked", cashback_receivable_atomic: "Cashback receivable",
  // Settlement funding is never presented as attribution of financial profit.
  gross_sell_settlement_atomic: "Gross sell proceeds", venue_funded_sell_atomic: "Venue-funded proceeds",
  synthetic_funded_sell_atomic: "Synthetic proceeds", valuation_status: "Valuation coverage",
  unvalued_open_position_count: "Unvalued", filled_sell_count: "Successful sells",
  favorable_slippage_count: "Favorable slippage", adverse_slippage_count: "Adverse slippage",
};

export const label = (key: string) => t(labels[key] ?? key.replaceAll('_', ' '));
export const familyLabel = (family: string) => ({ PUMPFUN_SNIPING: 'Pump.fun Sniping', PUMPFUN_COPY_BUY: 'Pump.fun Copy Buy', FIRST_SWAP: 'FirstSwap' }[family] ?? family);
