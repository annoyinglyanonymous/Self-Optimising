async function loadOverview() {
  const days = getWindowDays();
  try {
    const [stats, ts] = await Promise.all([
      api(`/api/dashboard/stats?days=${days}`),
      api(`/api/dashboard/timeseries?days=${Math.min(days, 30)}`),
    ]);
    renderStats(stats);
    renderTimeseries(ts);
  } catch (e) {
    console.error(e);
  }
}

function renderStats(s) {
  $("#kpi-total-leads").textContent = num(s.total_leads);
  $("#kpi-leads-window").textContent = `+${num(s.leads_in_window)} in last ${s.window_days}d`;
  $("#kpi-touches").textContent = num(s.touches_in_window);
  $("#kpi-sent").textContent = num(s.events.sent);
  $("#kpi-open-rate").textContent = pct(s.rates.open_rate);
  $("#kpi-opened").textContent = `${num(s.events.opened)} opened`;
  $("#kpi-reply-rate").textContent = pct(s.rates.reply_rate);
  $("#kpi-replied").textContent = `${num(s.events.replied)} replies`;
  $("#kpi-positive-rate").textContent = pct(s.rates.positive_rate);
  $("#kpi-positive").textContent = `${num(s.events.positive)} positive · ${num(s.events.negative)} negative`;

  const breakdown = $("#event-breakdown");
  breakdown.innerHTML = "";
  const counts = s.event_counts || {};
  const keys = Object.keys(counts).sort();
  if (!keys.length) {
    breakdown.innerHTML = '<div class="empty">No events in this window</div>';
    return;
  }
  for (const k of keys) {
    const div = document.createElement("div");
    div.className = "row";
    div.innerHTML = `<span class="name">${k}</span><span class="count">${num(counts[k])}</span>`;
    breakdown.appendChild(div);
  }
}

function renderTimeseries(data) {
  $("#ts-window-label").textContent = `${data.days}d`;
  const canvas = $("#ts-chart");
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const series = data.series || [];
  if (!series.length) {
    ctx.fillStyle = "#747878";
    ctx.font = "12px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("NO DATA IN WINDOW", W / 2, H / 2);
    return;
  }

  const padL = 40, padR = 16, padT = 16, padB = 28;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const maxVal = Math.max(
    1,
    ...series.flatMap((d) => [d.sent, d.opened, d.replied])
  );
  const xStep = series.length > 1 ? innerW / (series.length - 1) : 0;

  ctx.strokeStyle = "#d8e1ee";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padT + (innerH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(W - padR, y);
    ctx.stroke();
    ctx.fillStyle = "#747878";
    ctx.font = "10px Inter, sans-serif";
    ctx.textAlign = "right";
    const val = Math.round((maxVal * (4 - i)) / 4);
    ctx.fillText(String(val), padL - 6, y + 3);
  }

  const labelStep = Math.max(1, Math.ceil(series.length / 7));
  ctx.fillStyle = "#747878";
  ctx.font = "10px Inter, sans-serif";
  ctx.textAlign = "center";
  series.forEach((d, i) => {
    if (i % labelStep !== 0 && i !== series.length - 1) return;
    const x = padL + i * xStep;
    const label = d.date.slice(5);
    ctx.fillText(label, x, H - padB + 14);
  });

  function plotLine(key, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    series.forEach((d, i) => {
      const x = padL + i * xStep;
      const y = padT + innerH - (d[key] / maxVal) * innerH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    ctx.fillStyle = color;
    series.forEach((d, i) => {
      const x = padL + i * xStep;
      const y = padT + innerH - (d[key] / maxVal) * innerH;
      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  plotLine("sent", "#000000");
  plotLine("opened", "#006d35");
  plotLine("replied", "#c76c00");
}

window.onWindowChange = () => loadOverview();
window.onRefresh = () => loadOverview();

loadOverview();
