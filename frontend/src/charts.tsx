import { t, useLocale, localeTag } from './i18n';
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Line, LineChart, ReferenceDot } from 'recharts';
import { useState } from 'react';
import { Button, Card, Empty, Pager } from './ui';
import { atomic, axisAtomic, percent } from './format';
import type { Analytics, MarketChart } from './result-contracts';
import { marketViewport } from './chart-view';

// Static theme colors avoid dynamically injected stylesheet elements under the strict CSP.
const colors = ['var(--accent)', 'var(--teal)', 'var(--rose)', 'var(--gold)', 'var(--lavender)', 'var(--muted)'];
const names: Record<string, string> = { FILLED: "Filled", FAILED: "Execution failed", REJECTED: "Rejected", CLOSED: "Closed", EXHAUSTED: "Attempts exhausted", COOLDOWN_SKIPPED: 'Cooldown', PROFIT: "Profit", LOSS: "Loss", FLAT: "Unchanged", FAVORABLE: "Better than reference", ADVERSE: "Worse than reference", UNCHANGED: "Unchanged" };
const display = (name: string) => name.split(':').map(part => t(names[part] ?? part)).join(' · ');
const populations: Record<string, string> = { entries: "entries", entries_with_exit_decision: "exit decisions", attempts: "attempts", failed_or_rejected_attempts: "unsuccessful attempts", attempts_with_both_quotes: "attempts with both quotes", valued_realized_entries: "entries with realized valuation" };

export function DistributionChart({ title, group, donut = false }: { title: string; group?: Analytics['distributions'][number]; donut?: boolean }) {
  useLocale();
  if (!group) return <Card><h3>{title}</h3><Empty title={t("Analytics unavailable")} /></Card>;
  const total = BigInt(group.total);
  const data = group.items.map(item => ({ ...item, name: display(item.label), value: total ? Number(BigInt(item.count) * 1_000_000n / total) : 0 }));
  // Geometry uses bounded normalized values; labels and tooltip retain exact counts.
  return <Card><div className="card-heading"><h3>{title}</h3><span>{group.total} {t(populations[group.population] ?? group.population)}</span></div>
    {!data.length ? <Empty title={t("No matching records")} /> : <><div className="chart-box" role="img" aria-label={`${title}: ${data.map(item => `${item.name} ${item.count}`).join(', ')}`}>
      <ResponsiveContainer width="100%" height="100%">{donut ? <PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius="60%" outerRadius="85%" paddingAngle={3} stroke="none" isAnimationActive={false}>
        {data.map((item, index) => <Cell key={item.label} fill={colors[index % colors.length]} />)}</Pie><Tooltip content={({ active, payload }) => active && payload?.[0] ? <div className="chart-tooltip">{payload[0].name}<strong>{payload[0].payload.count}</strong></div> : null} /></PieChart>
      : <BarChart data={data} layout="vertical" margin={{ left: 10, right: 25 }}><CartesianGrid stroke="var(--border)" horizontal={false} /><XAxis type="number" hide /><YAxis type="category" dataKey="name" width={140} tick={{ fill: 'var(--muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
        {/* The axis describes proportions; the adjacent table exposes every precise count. */}
        <Bar dataKey="value" radius={[0, 5, 5, 0]} maxBarSize={26} isAnimationActive={false}>{data.map((item, index) => <Cell key={item.label} fill={colors[index % colors.length]} />)}</Bar><Tooltip cursor={false} content={({ active, payload }) => active && payload?.[0] ? <div className="chart-tooltip">{payload[0].payload.name}<strong>{payload[0].payload.count}</strong></div> : null} /></BarChart>}
      </ResponsiveContainer></div><div className="chart-legend">{data.map((item, index) => <div key={item.label}><span className={`legend-dot color-${index % colors.length}`} /><span>{item.name}</span><strong>{item.count}</strong><small>{percent(item.count, group.total)}</small></div>)}</div></>}
  </Card>;
}

export function AmountChart({ title, items }: { title: string; items: { label: string; value: string | null }[] }) {
  useLocale();
  const present = items.filter((item): item is { label: string; value: string } => item.value !== null);
  const maximum = present.reduce((max, item) => { const value = BigInt(item.value); return value > max ? value : max; }, 0n);
  const data = present.map(item => ({ ...item, height: maximum ? Number(BigInt(item.value) * 1_000_000n / maximum) : 0 }));
  // Money is rendered from the original exact amount, while chart heights use a normalized range.
  return <Card><h3>{title}</h3>{!present.length ? <Empty title={t("No data for this result")} /> : <><div className="chart-box compact" role="img" aria-label={present.map(item => `${item.label}: ${item.value} atomic`).join(', ')}>
    <ResponsiveContainer width="100%" height="100%"><BarChart data={data}><CartesianGrid stroke="var(--border)" vertical={false} /><XAxis dataKey="label" tick={{ fill: 'var(--muted)', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis hide /><Bar dataKey="height" radius={[5, 5, 0, 0]} maxBarSize={50} isAnimationActive={false}>
      {data.map((item, index) => <Cell key={item.label} fill={colors[index % colors.length]} />)}</Bar><Tooltip cursor={false} content={({ active, payload }) => active && payload?.[0] ? <div className="chart-tooltip">{payload[0].payload.label}<strong>{atomic(payload[0].payload.value)} SOL</strong><small>{payload[0].payload.value} lamports</small></div> : null} /></BarChart></ResponsiveContainer>
    </div><div className="chart-legend">{present.map((item, index) => <div key={item.label}><span className={`legend-dot color-${index % colors.length}`} /><span>{item.label}</span><strong title={`${item.value} lamports`}>{atomic(item.value)} SOL</strong></div>)}</div></>}
  </Card>;
}

export function MarketHistoryChart({ chart }: { chart: MarketChart }) {
  useLocale();
  const [page, setPage] = useState(0);
  const [aroundTrade, setAroundTrade] = useState(true);
  // Zoom changes only local geometry; the retained history is fetched once for this selection.
  const { rank, boundaries, data, scale, atTick } = marketViewport(chart, aroundTrade);
  return <Card><div className="card-heading"><h3>{t("Market-cap history")}</h3><span>{t("Full supply · SOL")}</span></div><div className="actions"><Button aria-pressed={aroundTrade} tone={aroundTrade ? 'primary' : 'default'} onClick={() => setAroundTrade(true)}>{t("Around trade")}</Button><Button aria-pressed={!aroundTrade} tone={!aroundTrade ? 'primary' : 'default'} onClick={() => setAroundTrade(false)}>{t("Full history")}</Button></div><p className="subtle">{t("Transaction order. Horizontal intervals are equal; hover to see event time. The vertical scale adjusts automatically.")}</p>
    <div className="market-chart" role="img" aria-label={t("Market-cap history with the signal and actual attempt outcomes")}>
      <ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 28, right: 30, bottom: 16, left: 10 }}><CartesianGrid stroke="var(--border)" vertical={false} /><XAxis type="number" dataKey="x" domain={[0, Math.max(1, boundaries.length - 1)]} tick={false} axisLine={false} /><YAxis domain={[0, 1_000_000]} tickFormatter={value => axisAtomic(atTick(Number(value)))} tick={{ fill: 'var(--muted)', fontSize: 11 }} axisLine={false} tickLine={false} width={80} />
        <Line type="stepAfter" dataKey="y" stroke="var(--accent)" strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls={false} />
        {/* Marker x uses its own exact boundary even if it lands between historical market trades. */}
        {chart.markers.map((marker, index) => <ReferenceDot key={`${marker.kind}-${index}`} x={rank.get(marker.point.position.boundary_ordinal)!} y={scale(marker.point.market_cap_atomic)} r={6} fill={marker.kind === 'SIGNAL' ? 'var(--gold)' : marker.status === 'FILLED' ? 'var(--teal)' : 'var(--rose)'} stroke="var(--card)" strokeWidth={2} label={{ value: marker.kind === 'SIGNAL' ? t("Signal") : `${marker.kind} ${marker.attempt}`, fill: 'var(--text)', position: index % 2 ? 'bottom' : 'top', fontSize: 11 }} />)}
        <Tooltip content={({ active, payload }) => active && payload?.[0] ? <div className="chart-tooltip"><strong>{atomic(payload[0].payload.market_cap_atomic)} SOL</strong><span>{t("Block")} {payload[0].payload.position.block_ordinal} · tx {payload[0].payload.position.transaction_index}</span><small>{new Date(Number(BigInt(payload[0].payload.block_time_ns) / 1_000_000n)).toLocaleString(localeTag())}</small></div> : null} />
      </LineChart></ResponsiveContainer>
    </div><p className="subtle">{t("The curve ends at completion / migration. Reserve-based market cap differs from your trade execution price.")}</p>
    <details><summary>{t("Exact chart points and events")}</summary><div className="table-scroll"><table aria-label={t("Chart events")}><thead><tr><th>{t("Event")}</th><th>{t("Outcome")}</th><th>Boundary</th><th>{t("Market cap, lamports")}</th></tr></thead><tbody>{chart.markers.map((marker, index) => <tr key={index}><td>{marker.kind} {marker.attempt}</td><td>{marker.failure_code ?? marker.status}</td><td>{marker.point.position.boundary_ordinal}</td><td>{marker.point.market_cap_atomic}</td></tr>)}</tbody></table></div>
      {/* The accessible raw series is paged; opening details never creates thousands of DOM rows. */}
      <div className="table-scroll"><table aria-label={t("Historical points")}><thead><tr><th>Boundary</th><th>{t("Time, ns")}</th><th>{t("Market cap, lamports")}</th><th>Lifecycle</th></tr></thead><tbody>{chart.points.slice(page * 25, (page + 1) * 25).map(point => <tr key={point.position.boundary_ordinal}><td>{point.position.boundary_ordinal}</td><td>{point.block_time_ns}</td><td>{point.market_cap_atomic}</td><td>{point.lifecycle}</td></tr>)}</tbody></table></div><Pager index={page} count={chart.points.slice(page * 25, (page + 1) * 25).length} busy={false} previous={page ? () => setPage(page - 1) : undefined} next={(page + 1) * 25 < chart.points.length ? () => setPage(page + 1) : undefined} /></details>
  </Card>;
}
