/* ─── Thetis Dashboard — Frontend Logic ─── */

const POLL_MS = 1500;          // poll every 1.5s
let pollTimer = null;
let lastSignal = null;
let holdCount = 0;

// ─── DOM refs ───
const $signal      = document.getElementById('signal-display');
const $signalMeta  = document.getElementById('signal-meta');
const $signalCard  = document.getElementById('signal-card');
const $statusBadge = document.getElementById('status-badge');
const $statusText  = $statusBadge.querySelector('.status-text');
const $btnStart    = document.getElementById('btn-start');
const $btnStop     = document.getElementById('btn-stop');
const $ema9        = document.getElementById('ema9-value');
const $ema21       = document.getElementById('ema21-value');
const $rsi         = document.getElementById('rsi-value');
const $ema9Bar     = document.getElementById('ema9-bar');
const $ema21Bar    = document.getElementById('ema21-bar');
const $rsiNeedle   = document.getElementById('rsi-needle');
const $cash        = document.getElementById('cash-value');
const $bp          = document.getElementById('bp-value');
const $trades      = document.getElementById('trades-value');
const $iter        = document.getElementById('iter-value');
const $buyCount    = document.getElementById('buy-count');
const $sellCount   = document.getElementById('sell-count');
const $holdCount   = document.getElementById('hold-count');
const $logBody     = document.getElementById('log-body');
const $logCount    = document.getElementById('log-count');
const $posBody     = document.getElementById('positions-body');
const $posTable    = document.getElementById('positions-table');
const $posEmpty    = document.getElementById('positions-empty');
const $canvas      = document.getElementById('price-canvas');
const ctx          = $canvas.getContext('2d');

// ─── API helpers ───
async function apiPost(url, body = {}) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return res.json();
}

async function apiGet(url) {
    const res = await fetch(url);
    return res.json();
}

// ─── Start / Stop ───
async function startBot() {
    holdCount = 0;
    await apiPost('/api/start');
    beginPolling();
}

async function stopBot() {
    await apiPost('/api/stop');
}

function applyConfig() {
    const symbol = document.getElementById('cfg-symbol').value.trim() || 'AAPL';
    const qty    = parseFloat(document.getElementById('cfg-qty').value) || 1;
    const delay  = parseInt(document.getElementById('cfg-delay').value) || 10;
    holdCount = 0;
    apiPost('/api/start', { symbol, trade_qty: qty, loop_delay: delay }).then(() => {
        beginPolling();
    });
}

// ─── Polling ───
function beginPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(fetchState, POLL_MS);
    fetchState();
}

async function fetchState() {
    try {
        const s = await apiGet('/api/state');
        render(s);
    } catch (e) {
        console.error('Poll error', e);
    }
}

// ─── Render ───
function render(s) {
    // Status badge
    if (s.running) {
        $statusBadge.classList.add('running');
        $statusText.textContent = 'Running';
        $btnStart.disabled = true;
        $btnStop.disabled = false;
    } else {
        $statusBadge.classList.remove('running');
        $statusText.textContent = 'Offline';
        $btnStart.disabled = false;
        $btnStop.disabled = true;
    }

    // Signal
    const sig = s.last_signal || '—';
    $signal.textContent = sig;
    $signal.className = 'signal-display ' + sig.toLowerCase();
    if (sig !== lastSignal && lastSignal !== null) {
        $signalCard.classList.remove('flash');
        void $signalCard.offsetWidth; // reflow
        $signalCard.classList.add('flash');
    }
    lastSignal = sig;
    $signalMeta.textContent = s.running
        ? `Iteration #${s.iteration} · ${s.symbol}`
        : 'Waiting for data…';

    // Indicators
    $ema9.textContent  = s.last_ema9.toFixed(4);
    $ema21.textContent = s.last_ema21.toFixed(4);
    $rsi.textContent   = s.last_rsi.toFixed(2);

    // EMA bars (normalise to 0–100 range based on typical price)
    const maxPrice = Math.max(s.last_ema9, s.last_ema21, 1);
    $ema9Bar.style.width  = Math.min(100, (s.last_ema9  / (maxPrice * 1.2)) * 100) + '%';
    $ema21Bar.style.width = Math.min(100, (s.last_ema21 / (maxPrice * 1.2)) * 100) + '%';

    // RSI needle
    $rsiNeedle.style.left = Math.min(100, Math.max(0, s.last_rsi)) + '%';

    // Metrics
    $cash.textContent   = '$' + Number(s.cash).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    $bp.textContent     = '$' + Number(s.buying_power).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    $trades.textContent = s.total_trades;
    $iter.textContent   = s.iteration;

    // Breakdown
    $buyCount.textContent  = s.buy_count;
    $sellCount.textContent = s.sell_count;
    // Calculate hold count from log
    holdCount = (s.trade_log || []).filter(e => e.signal === 'HOLD').length;
    $holdCount.textContent = holdCount;

    // Positions
    const positions = s.positions || [];
    if (positions.length === 0) {
        $posTable.style.display = 'none';
        $posEmpty.style.display = 'block';
    } else {
        $posTable.style.display = 'table';
        $posEmpty.style.display = 'none';
        $posBody.innerHTML = positions.map(p => `
            <tr>
                <td>${p.symbol}</td>
                <td>${p.qty}</td>
                <td>$${Number(p.avg_entry_price || p.avg_price || 0).toFixed(2)}</td>
                <td>$${Number(p.market_value || 0).toFixed(2)}</td>
                <td style="color:${(p.unrealized_pl || 0) >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'}">
                    $${Number(p.unrealized_pl || 0).toFixed(2)}
                </td>
            </tr>
        `).join('');
    }

    // Trade log
    const log = s.trade_log || [];
    $logCount.textContent = log.length + ' entries';
    $logBody.innerHTML = log.map(e => {
        const signalClass = (e.signal || '').toLowerCase();
        return `<tr>
            <td>${e.iteration || ''}</td>
            <td>${e.timestamp || ''}</td>
            <td><span class="signal-pill ${signalClass}">${e.signal || '—'}</span></td>
            <td>${e.close != null ? e.close.toFixed(2) : '—'}</td>
            <td>${e.ema9 != null  ? e.ema9.toFixed(4) : '—'}</td>
            <td>${e.ema21 != null ? e.ema21.toFixed(4) : '—'}</td>
            <td>${e.rsi != null   ? e.rsi.toFixed(2) : '—'}</td>
            <td>${e.action || e.error || '—'}</td>
            <td>${e.cash != null  ? '$' + Number(e.cash).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}) : '—'}</td>
        </tr>`;
    }).join('');

    // Chart
    drawChart(s.price_history || [], s.signal_history || []);
}

// ─── Mini Chart ───
function drawChart(prices, signals) {
    const dpr = window.devicePixelRatio || 1;
    const rect = $canvas.getBoundingClientRect();
    $canvas.width  = rect.width  * dpr;
    $canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.clearRect(0, 0, W, H);

    if (prices.length < 2) {
        ctx.fillStyle = '#64748b';
        ctx.font = '13px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Waiting for price data…', W / 2, H / 2);
        return;
    }

    const vals = prices.map(p => p.price);
    const min  = Math.min(...vals) * 0.998;
    const max  = Math.max(...vals) * 1.002;
    const range = max - min || 1;

    const padL = 10, padR = 10, padT = 14, padB = 14;
    const cW = W - padL - padR;
    const cH = H - padT - padB;

    function x(i) { return padL + (i / (vals.length - 1)) * cW; }
    function y(v) { return padT + cH - ((v - min) / range) * cH; }

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const yy = padT + (i / 4) * cH;
        ctx.beginPath();
        ctx.moveTo(padL, yy);
        ctx.lineTo(W - padR, yy);
        ctx.stroke();
    }

    // Gradient fill under line
    const grad = ctx.createLinearGradient(0, padT, 0, H);
    grad.addColorStop(0, 'rgba(99,102,241,0.25)');
    grad.addColorStop(1, 'rgba(99,102,241,0)');

    ctx.beginPath();
    ctx.moveTo(x(0), y(vals[0]));
    for (let i = 1; i < vals.length; i++) {
        ctx.lineTo(x(i), y(vals[i]));
    }
    ctx.lineTo(x(vals.length - 1), H - padB);
    ctx.lineTo(x(0), H - padB);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Price line
    ctx.beginPath();
    ctx.moveTo(x(0), y(vals[0]));
    for (let i = 1; i < vals.length; i++) {
        ctx.lineTo(x(i), y(vals[i]));
    }
    ctx.strokeStyle = '#6366f1';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // Signal dots
    const sigMap = {};
    signals.forEach(s => { sigMap[s.t] = s.signal; });
    prices.forEach((p, i) => {
        const sig = sigMap[p.t];
        if (sig === 'BUY' || sig === 'SELL') {
            ctx.beginPath();
            ctx.arc(x(i), y(p.price), 5, 0, Math.PI * 2);
            ctx.fillStyle = sig === 'BUY' ? '#10b981' : '#ef4444';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 1.5;
            ctx.stroke();
        }
    });

    // Latest price label
    const lastVal = vals[vals.length - 1];
    ctx.fillStyle = '#e2e8f0';
    ctx.font = '600 11px "JetBrains Mono", monospace';
    ctx.textAlign = 'right';
    ctx.fillText('$' + lastVal.toFixed(2), W - padR, y(lastVal) - 8);
}

// Start polling on page load
beginPolling();

// Handle window resize for chart
window.addEventListener('resize', () => {
    // will redraw on next poll
});
