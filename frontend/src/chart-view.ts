import type { MarketChart } from './result-contracts';

export function marketViewport(chart: MarketChart, aroundTrade: boolean) {
  // The viewport selects retained points only, with the previous state for step continuity.
  const before = BigInt(chart.markers[0].point.block_time_ns) - 20_000_000_000n;
  const after = BigInt(chart.markers.at(-1)!.point.block_time_ns) + 20_000_000_000n;
  const first = chart.points.findIndex(point => BigInt(point.block_time_ns) >= before);
  const last = chart.points.findIndex(point => BigInt(point.block_time_ns) > after);
  const points = aroundTrade ? chart.points.slice(Math.max(0, first - 1), last < 0 ? undefined : last + 1) : chart.points;
  // Canonical transaction ranks distinguish events that share one historical timestamp.
  const boundaries = [...new Set([...points, ...chart.markers.map(marker => marker.point)].map(point => point.position.boundary_ordinal))];
  boundaries.sort((a, b) => BigInt(a) < BigInt(b) ? -1 : 1);
  const rank = new Map(boundaries.map((key, index) => [key, index]));
  const terminal = chart.points.find(point => point.lifecycle !== 'ACTIVE');
  const line = points.filter(point => !terminal || BigInt(point.position.boundary_ordinal) <= BigInt(terminal.position.boundary_ordinal));
  // Scale relative exact integers before converting to bounded drawing geometry.
  const amounts = [...line, ...chart.markers.map(marker => marker.point)].map(point => BigInt(point.market_cap_atomic));
  const minimum = amounts.reduce((min, amount) => amount < min ? amount : min);
  const maximum = amounts.reduce((max, amount) => amount > max ? amount : max);
  const spread = maximum - minimum;
  const padding = (spread || maximum) / 20n || 1n;
  // Auto range makes small changes visible without changing a single stored market-cap value.
  const low = minimum > padding ? minimum - padding : 0n, high = maximum + padding;
  const scale = (value: string) => Number((BigInt(value) - low) * 1_000_000n / (high - low));
  const atTick = (tick: number) => low + BigInt(Math.round(tick)) * (high - low) / 1_000_000n;
  return { rank, boundaries, data: line.map(point => ({ ...point, x: rank.get(point.position.boundary_ordinal)!, y: scale(point.market_cap_atomic) })), scale, atTick };
}
