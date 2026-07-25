/* MetaTrader‑style JavaScript – UI handling and chart */

/* Configuration */
const POLL_MS = 1500; // Poll every 1.5 seconds
let pollTimer = null;
let lastSignal = null;

/* DOM references */
const $statusBadge = document.getElementById('mt-status');
const $statusDot   = $statusBadge.querySelector('.mt-status-dot');
const $statusText  = $statusBadge.querySelector('.mt-status-text');
const $startBtn    = document.getElementById('mt-start-btn');
const $stopBtn     = document.getElementById('mt-stop-btn');
const $symbolInp   = document.getElementById('mt-symbol');
const $qtyInp      = document.getElementById('mt-qty');
const $delayInp    = document.getElementById('mt-delay');

const $signal      = document.getElementById('mt-signal');
const $signalMeta  = document.getElementById('mt-signal-meta');
const $signalPanel = document.getElementById('mt-signal-panel');

const $cash        = document.getElementById('mt-cash');
const $bp          = document.getElementById('mt-bp');
const $trades      = document.getElementById('mt-trades');
const $iter        = document.getElementById('mt-iter');

const $logBody     = document.getElementById('mt-log-body').querySelector('tbody');
const $logCount    = document.getElementById('mt-log-count');

const $canvas      = document.getElementById('mt-price-canvas');
const ctx          = $canvas.getContext('2d');

/* API helpers */
async function apiGet(url){
    const r = await fetch(url);
    return r.json();
}
async function apiPost(url, body={}){
    const r = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(body)
    });
    return r.json();
}

/* Bot control */
async function startBot(){
    const payload = {
        symbol: $symbolInp.value.trim() || 'AAPL',
        trade_qty: Number($qtyInp.value) || 1,
        loop_delay: Number($delayInp.value) || 10
    };
    await apiPost('/api/start', payload);
    beginPolling();
}

async function stopBot(){
    await apiPost('/api/stop');
    // UI will update on next poll
}

/* Event listeners */
$startBtn.addEventListener('click', startBot);
$stopBtn.addEventListener('click', stopBot);

/* Polling */
function beginPolling(){
    if(pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(fetchState, POLL_MS);
    fetchState();
}

async function fetchState(){
    try {
        const s = await apiGet('/api/state');
        render(s);
    } catch(e){
        console.error('Polling error', e);
    }
}

/* Rendering */
function render(s){
    // Status badge
    if(s.running){
        $statusBadge.classList.remove('offline');
        $statusBadge.classList.add('online');
        $statusText.textContent = 'Online';
        $startBtn.disabled = true;
        $stopBtn.disabled = false;
    } else {
        $statusBadge.classList.remove('online');
        $statusBadge.classList.add('offline');
        $statusText.textContent = 'Offline';
        $startBtn.disabled = false;
        $stopBtn.disabled = true;
    }

    // Signal display
    const sig = s.last_signal || '—';
    $signal.textContent = sig;
    $signal.className = 'mt-signal-display ' + sig.toLowerCase();
    if(sig !== lastSignal && lastSignal !== null){
        $signalPanel.classList.remove('flash');
        void $signalPanel.offsetWidth; // reflow
        $signalPanel.classList.add('flash');
    }
    lastSignal = sig;
    $signalMeta.textContent = s.running ? `Iteration #${s.iteration} • ${s.symbol}` : 'Waiting for data…';

    // Metrics
    $cash.textContent = '$' + Number(s.cash).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    $bp.textContent   = '$' + Number(s.buying_power).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    $trades.textContent = s.total_trades;
    $iter.textContent   = s.iteration;

    // Trade log
    const log = s.trade_log || [];
    $logCount.textContent = `${log.length} entries`;
    $logBody.innerHTML = log.map(e => {
        const sigClass = (e.signal||'').toLowerCase();
        return `<tr>
            <td>${e.iteration||''}</td>
            <td>${e.timestamp||''}</td>
            <td><span class="signal-pill ${sigClass}">${e.signal||'—'}</span></td>
            <td>${e.close!=null? e.close.toFixed(2) : '—'}</td>
            <td>${e.action||e.error||'—'}</td>
            <td>${e.cash!=null? '$'+Number(e.cash).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—'}</td>
        </tr>`;
    }).join('');

    // Chart – reuse drawChart from previous version (adjust IDs)
    drawChart(s.price_history||[], s.signal_history||[]);
}

/* Chart drawing – similar to original implementation */
function drawChart(prices, signals){
    const dpr = window.devicePixelRatio || 1;
    const rect = $canvas.getBoundingClientRect();
    $canvas.width = rect.width * dpr;
    $canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    ctx.clearRect(0,0,W,H);

    if(prices.length < 2){
        ctx.fillStyle = '#a0a0a0';
        ctx.font = '13px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Waiting for price data…', W/2, H/2);
        return;
    }
    const vals = prices.map(p=>p.price);
    const min = Math.min(...vals)*0.998;
    const max = Math.max(...vals)*1.002;
    const range = max-min || 1;
    const pad = {l:10, r:10, t:14, b:14};
    const cW = W - pad.l - pad.r;
    const cH = H - pad.t - pad.b;
    const x = i => pad.l + (i/(vals.length-1))*cW;
    const y = v => pad.t + cH - ((v-min)/range)*cH;

    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 1;
    for(let i=0;i<=4;i++){
        const yy = pad.t + (i/4)*cH;
        ctx.beginPath();
        ctx.moveTo(pad.l, yy);
        ctx.lineTo(W-pad.r, yy);
        ctx.stroke();
    }

    // Gradient fill under line
    const grad = ctx.createLinearGradient(0, pad.t, 0, H);
    grad.addColorStop(0,'rgba(99,102,241,0.25)');
    grad.addColorStop(1,'rgba(99,102,241,0)');
    ctx.beginPath();
    ctx.moveTo(x(0), y(vals[0]));
    for(let i=1;i<vals.length;i++) ctx.lineTo(x(i), y(vals[i]));
    ctx.lineTo(x(vals.length-1), H-pad.b);
    ctx.lineTo(x(0), H-pad.b);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Price line
    ctx.beginPath();
    ctx.moveTo(x(0), y(vals[0]));
    for(let i=1;i<vals.length;i++) ctx.lineTo(x(i), y(vals[i]));
    ctx.strokeStyle = '#6366f1';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Signal dots
    const sigMap = {};
    signals.forEach(s=>{ sigMap[s.t] = s.signal; });
    prices.forEach((p,i)=>{
        const sig = sigMap[p.t];
        if(sig==='BUY' || sig==='SELL'){
            ctx.beginPath();
            ctx.arc(x(i), y(p.price), 5, 0, Math.PI*2);
            ctx.fillStyle = sig==='BUY' ? '#10b981' : '#ef4444';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 1.5;
            ctx.stroke();
        }
    });

    // Latest price label
    const lastVal = vals[vals.length-1];
    ctx.fillStyle = '#e2e8f0';
    ctx.font = '600 11px "JetBrains Mono", monospace';
    ctx.textAlign = 'right';
    ctx.fillText('$'+lastVal.toFixed(2), W-pad.r, y(lastVal)-8);
}

/* Start polling when page loads */
window.addEventListener('load', beginPolling);
window.addEventListener('resize', () => {/* next poll will redraw */});
