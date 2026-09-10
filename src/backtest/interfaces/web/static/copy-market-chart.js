"use strict";

// Display helpers have no network or replay authority; callers supply verified projections.
globalThis.CopyMarketChart = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const policy = "post-transaction-total-supply-market-cap-lamports-floor/v1";
  const $ = (id) => document.getElementById(id);

  // Wide quantities stay exact until conversion to a bounded pixel ratio.
  function integer(value) {
    if (typeof value !== "string" || !/^(?:0|-?[1-9][0-9]*)$/.test(value) || value.length > 40) {
      throw new Error("Некорректное целое число в результате");
    }
    return BigInt(value);
  // Only validated canonical strings reach the arbitrary-precision parser.
  }

  // Round only for display; preserve the exact source value separately in response data.
  function sol(value, digits = 6) {
    if (value === null) return "Нет оценки";
    const amount = typeof value === "bigint" ? value : integer(value);
    const magnitude = amount < 0n ? -amount : amount;
    // Fixed decimal digits avoid scientific notation and floating-point money arithmetic.
    const scale = 10n ** BigInt(9 - digits);
    const rounded = (magnitude + scale / 2n) / scale;
    const unit = 10n ** BigInt(digits);
    return `${amount < 0n ? "−" : ""}${rounded / unit}.${String(rounded % unit).padStart(digits, "0")}`;
  }

  // Only a fixed-point fraction in [0, 1] becomes a floating-point SVG coordinate.
  function fraction(value, span) {
    if (span <= 0n) return 0;
    return Number(value * 1000000n / span) / 1000000;
  }

  // Construct text and attributes directly; server strings never enter HTML parsing.
  function svg(tag, attributes = {}, text = null) {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (text !== null) node.textContent = text;
    // SVG titles and labels use text nodes, including addresses supplied by the API.
    return node;
  }

  // ChainPosition's versioned transaction boundary packs tx_index + 1 into the low word.
  function boundary(position) {
    return (BigInt(position.block_ordinal) << 32n) + BigInt(position.transaction_index) + 1n;
  }

  // Dates are labels from source nanoseconds, not invented event availability timestamps.
  function time(ns, full = false) {
    const iso = new Date(Number(BigInt(ns) / 1000000n)).toISOString();
    return full ? `${iso.slice(0, 10)} ${iso.slice(11, 19)}` : iso.slice(11, 19);
  }

  // API identities and series bounds are rechecked before a new dialog becomes visible.
  function validate(data, run, record) {
    if (data.contract_schema !== "pumpfun-copy-market-cap/v1" || data.market_cap_policy !== policy) {
      throw new Error("Неизвестный формат графика");
    }
    if (data.run_artifact_id !== run || data.position_id !== record.position_id || data.asset_id !== record.asset_id) {
      // A correct schema alone does not prove which token or run the chart belongs to.
      throw new Error("График относится к другому сигналу");
    }
    // SOL units and bounded arrays are mandatory even for an empty-looking result.
    if (data.quote_asset_id !== "SOL" || !/^[0-9a-f]{64}$/.test(data.snapshot_id)) throw new Error("Неверный источник графика");
    if (!Array.isArray(data.points) || data.points.length < 1 || data.points.length > 4000) throw new Error("Неверная длина истории");
    if (!Array.isArray(data.markers) || data.markers.length !== record.attempts.length + 1 || data.markers.length > 6) throw new Error("Неверное число событий");
    let lastKey = -1n, lastTime = -1n;
    // Same-second states remain ordered by chain position; no invented subsecond spread.
    for (const point of data.points) {
      validatePoint(point, record);
      const key = boundary(point.position), timestamp = integer(point.block_time_ns);
      if (key <= lastKey || timestamp < lastTime) throw new Error("Нарушен порядок истории");
      [lastKey, lastTime] = [key, timestamp];
    // Equal source timestamps keep their original chain order rather than artificial spacing.
    }
    // Attempt identity, status and actual coordinate come from the row already on screen.
    data.markers.forEach((marker, index) => {
      validatePoint(marker.point, record);
      const attempt = record.attempts[index - 1];
      const coordinate = index === 0 ? record.signal_position : attempt.landing_position || attempt.decision_position;
      if (boundary(marker.point.position) !== boundary(coordinate)) throw new Error("Неверная точка события");
      // Rejections are decisions; only landed FILLED attempts receive entry/exit shapes.
      const expected = index === 0 ? ["SIGNAL", "OBSERVED_SOURCE", null, null] : [attempt.side, attempt.status, Number(attempt.attempt), attempt.failure_code];
      if (JSON.stringify([marker.kind, marker.status, marker.attempt, marker.failure_code]) !== JSON.stringify(expected)) throw new Error("Неверный исход события");
      const key = boundary(marker.point.position);
      if (key < boundary(data.points[0].position) || key > lastKey) throw new Error("Событие вне истории");
    });
    // Return only after every recorded attempt matches its displayed marker.
    return data;
  }

  // Validate the exact network, numeric range and closed lifecycle vocabulary of each point.
  function validatePoint(point, record) {
    const position = point.position, signal = record.signal_position;
    if (position.network_id !== signal.network_id || position.position_schema_id !== signal.position_schema_id) throw new Error("График другой сети");
    if (position.event_index !== null || !Number.isInteger(position.block_ordinal) || !Number.isInteger(position.transaction_index)) throw new Error("Неверная координата");
    if (position.block_ordinal < 0 || position.block_ordinal >= 2 ** 32 || position.transaction_index < 0 || position.transaction_index >= 2 ** 32 - 1) throw new Error("Координата вне диапазона");
    // Timestamp range matches the canonical Int64 contract and the browser Date range.
    const ns = integer(point.block_time_ns), cap = integer(point.market_cap_atomic);
    if (ns < 0n || ns >= 1n << 63n || cap < 0n || cap >= 1n << 128n) throw new Error("Значение вне диапазона");
    if (!["ACTIVE", "COMPLETED", "MIGRATED"].includes(point.lifecycle)) throw new Error("Неизвестное состояние кривой");
  }

  // Overview bars use only whole-run summary operands; page filtering never changes them.
  function bars(target, entries, monetary = false) {
    const values = entries.map((entry) => entry[1] === null ? null : integer(entry[1]));
    const maximum = values.reduce((max, value) => value === null ? max : (value < 0n ? -value : value) > max ? (value < 0n ? -value : value) : max, 1n);
    const root = svg("svg", { viewBox: `0 0 580 ${entries.length * 43 + 10}`, class: "chart-svg", role: "img", "aria-label": entries.map((entry) => `${entry[0]}: ${monetary ? `${sol(entry[1])} SOL` : entry[1]}`).join("; ") });
    const origin = monetary ? 373 : 220, width = monetary ? 103 : 256;
    // A fixed zero baseline lets positive and negative quantities share an honest scale.
    entries.forEach(([label, raw], index) => {
      const value = values[index], y = index * 43 + 23;
      root.append(svg("text", { x: 0, y, class: "chart-label" }, label));
      root.append(svg("line", { x1: origin, x2: origin, y1: y - 16, y2: y + 7, class: "copy-grid" }));
      if (value !== null) {
        // Bar pixels are ratios; the exact amount remains the adjacent textual label.
        const length = fraction(value < 0n ? -value : value, maximum) * width;
        root.append(svg("rect", { x: value < 0n ? origin - length : origin, y: y - 13, width: length, height: 18, rx: 3, class: `chart-bar ${value < 0n ? "danger" : "primary"}` }));
      }
      root.append(svg("text", { x: 575, y, class: "chart-value", "text-anchor": "end" }, monetary ? sol(raw) : String(raw)));
    // The adjacent label retains monetary units even when a bar is too small to see.
    });
    $(target).replaceChildren(root);
  }

  // Event descriptions are shared by marker labels, keyboard inspection and the table.
  function markerLabel(marker) {
    if (marker.kind === "SIGNAL") return "Сигнал лидера";
    if (marker.status === "FILLED") return marker.kind === "BUY" ? "Ваш вход" : "Ваш выход";
    return `${marker.kind === "BUY" ? "Покупка" : `Продажа ${marker.attempt}`} · ${marker.status === "REJECTED" ? "отклонена" : "не исполнена"}`;
  }

  // SVG and the event table expose the same detail text without introducing another data query.
  function describe(point, prefix = "История") {
    $("copy-chart-detail").textContent = `${prefix} · ${time(point.block_time_ns, true)} UTC · блок ${point.position.block_ordinal}, tx ${point.position.transaction_index} · ${sol(point.market_cap_atomic, 9)} SOL · ${point.lifecycle}`;
  }

  // Initial zoom includes the signal and every attempt; the full retained interval is one click away.
  function interval(data, zoom) {
    const first = BigInt(data.points[0].block_time_ns), last = BigInt(data.points.at(-1).block_time_ns);
    if (!zoom) return [first, last > first ? last : first + 1000000000n];
    const from = BigInt(data.markers[0].point.block_time_ns) - 20000000000n;
    const to = BigInt(data.markers.at(-1).point.block_time_ns) + 20000000000n;
    // A one-second visual range handles a single retained source timestamp without fabricating rows.
    return [from > first ? from : first, to < last ? to : last > first ? last : first + 1000000000n];
  }

  // Only the active curve and its terminal transition form a line; no PumpSwap continuation.
  function seriesPath(points, x, y) {
    let path = `M ${x(points[0])} ${y(points[0])}`;
    for (let index = 1; index < points.length; index += 1) {
      // Stop before carrying an inactive curve to the next proven clock boundary.
      if (points[index - 1].lifecycle !== "ACTIVE") break;
      path += ` H ${x(points[index])} V ${y(points[index])}`;
    }
    return path;
  }

// Local zoom changes the view, never the retained price series or marker identities.

  // Render one locally zoomed projection; clipping retains the prior as-of state at the left edge.
  function render(data, zoom = true) {
    const [from, to] = interval(data, zoom), span = to - from || 1n;
    const inside = data.points.filter((point) => BigInt(point.block_time_ns) >= from && BigInt(point.block_time_ns) <= to);
    const before = data.points.findLast((point) => BigInt(point.block_time_ns) < from);
    const after = data.points.find((point) => BigInt(point.block_time_ns) > to);
    // Boundary support points permit step rendering; no sampled price values are invented.
    const points = [...(before ? [before] : []), ...inside, ...(after ? [after] : [])];
    const amounts = points.map((point) => BigInt(point.market_cap_atomic));
    let low = amounts.reduce((a, b) => a < b ? a : b), high = amounts.reduce((a, b) => a > b ? a : b);
    const padding = (high - low) / 8n || high / 100n || 1n;
    [low, high] = [low > padding ? low - padding : 0n, high + padding];
    // Integer projection is bounded before the SVG renderer receives pixel coordinates.
    const x = (point) => 95 + fraction(BigInt(point.block_time_ns) - from, span) * 900;
    const y = (point) => 350 - fraction(BigInt(point.market_cap_atomic) - low, high - low) * 290;
    const root = svg("svg", { viewBox: "0 0 1080 410", class: "copy-market-svg", role: "img", "aria-label": "Маркеткап в SOL с сигналом и фактическими входами и выходами" });
    const defs = svg("defs"), clip = svg("clipPath", { id: "copy-plot-clip" });
    // Local clipping avoids leaking the off-screen full-history range into the zoom scale.
    clip.append(svg("rect", { x: 95, y: 35, width: 900, height: 330 }));
    defs.append(clip); root.append(defs);
    axes(root, from, span, low, high);
    const plot = svg("g", { "clip-path": "url(#copy-plot-clip)" });
    plot.append(svg("path", { d: seriesPath(points, x, y), class: "copy-market-line" }));
    // Terminal state is visibly labelled even if the selected record never obtained an entry.
    const terminal = points.find((point) => point.lifecycle !== "ACTIVE");
    if (terminal) {
      plot.append(svg("line", { x1: x(terminal), x2: x(terminal), y1: 40, y2: 350, class: "copy-terminal" }));
      plot.append(svg("text", { x: x(terminal) + 5, y: 51, class: "chart-label" }, terminal.lifecycle));
    }
    // Click any retained historical state; exact chain coordinates remain in the detail panel.
    for (const point of inside) {
      const dot = svg("circle", { cx: x(point), cy: y(point), r: 3, class: "copy-history-dot" });
      dot.append(svg("title", {}, `${time(point.block_time_ns)} · ${sol(point.market_cap_atomic, 9)} SOL · ${point.position.block_ordinal}/${point.position.transaction_index}`));
      dot.addEventListener("click", () => describe(point));
      plot.append(dot);
    // Historical point clicks inspect exact retained values rather than an interpolated price.
    }
    // At most six markers remain individually keyboard-accessible even at the same source second.
    data.markers.forEach((marker, index) => plot.append(markerShape(marker, index, x, y)));
    root.append(plot);
    $("copy-market-plot").replaceChildren(root);
    $("copy-chart-range").textContent = `${time(from, true)} — ${time(to, true)} UTC · ${data.points.length} состояний`;
    $("copy-chart-trade").setAttribute("aria-pressed", String(zoom));
    // The two zoom controls expose their selected state without another history request.
    $("copy-chart-all").setAttribute("aria-pressed", String(!zoom));
  }

  // Tick values derive from integer endpoints; each axis names its unit and time zone.
  function axes(root, from, span, low, high) {
    for (let i = 0; i <= 4; i += 1) {
      const y = 350 - i * 72.5, x = 95 + i * 225;
      root.append(svg("line", { x1: 95, x2: 995, y1: y, y2: y, class: "copy-grid" }));
      root.append(svg("text", { x: 85, y: y + 4, "text-anchor": "end", class: "chart-label" }, sol(low + (high - low) * BigInt(i) / 4n, 2)));
      // Capitalization ticks use the same integer domain as the plotted series.
      root.append(svg("text", { x, y: 378, "text-anchor": "middle", class: "chart-label" }, time(from + span * BigInt(i) / 4n)));
    }
    root.append(svg("text", { x: 95, y: 23, class: "chart-value" }, "Маркеткап, SOL"));
    root.append(svg("text", { x: 995, y: 400, "text-anchor": "end", class: "chart-label" }, "Время, UTC"));
  }

// Event shapes below add redundant outcome encoding to the historical line.

  // Labels are staggered, but every shape stays at its true historical x/y coordinate.
  function markerShape(marker, index, x, y) {
    const px = x(marker.point), py = y(marker.point);
    const tone = marker.kind === "SIGNAL" ? "signal" : marker.status !== "FILLED" ? "failed" : marker.kind.toLowerCase();
    const group = svg("g", { class: `copy-marker copy-${tone}`, tabindex: 0, role: "button", "aria-label": `${index + 1}. ${markerLabel(marker)}` });
    const shape = tone === "signal" ? `M ${px} ${py - 12} l 12 12 l -12 12 l -12 -12 Z` : tone === "buy" ? `M ${px} ${py - 8} l 8 15 h -16 Z` : `M ${px - 6} ${py - 6} l 12 12 m 0 -12 l -12 12`;
    // Exit circles and failure crosses differ by shape as well as color.
    group.append(tone === "sell" ? svg("circle", { cx: px, cy: py, r: 7 }) : svg("path", { d: shape }));
    group.append(svg("text", { x: px + 10, y: Math.max(65, py - 13 - index % 3 * 15), class: "copy-marker-number" }, String(index + 1)));
    const detail = () => describe(marker.point, `${index + 1}. ${markerLabel(marker)}${marker.failure_code ? ` · ${marker.failure_code}` : ""}`);
    group.addEventListener("click", detail);
    // Space/Enter provide the same inspection as the pointer action.
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); detail(); }
    });
    group.append(svg("title", {}, `${markerLabel(marker)} · ${time(marker.point.block_time_ns)} · ${sol(marker.point.market_cap_atomic, 9)} SOL`));
    return group;
  // A title supplies the same exact value for pointer-only inspection.
  }

  // The small public surface is also usable by deterministic browser-behavior tests.
  return Object.freeze({ integer, sol, boundary, time, validate, bars, render, markerLabel, describe });
})();
