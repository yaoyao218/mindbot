/**
 * Dashboard.js — 雙模態沉澱快照
 *
 * 記憶體防禦：
 *   window.mindBotCharts（Key = Canvas ID）
 *   渲染前呼叫 safelyDestroyChart() 根治 Canvas 重用警告
 *
 * 資料欄位對齊後端（weekly_scheduler.py）：
 *   arousal_curve : [{t: string, v: number}]   → 提取 .v
 *   past_baseline : [{t: string, v: number}] | undefined → 無資料時以本週平均防呆
 *   emotion_counts: { [label: string]: number }
 */

if (!window.mindBotCharts) window.mindBotCharts = {};

const PALETTE = ['#6366f1','#f59e0b','#3b82f6','#10b981','#ec4899','#8b5cf6'];

const EMOTION_LABEL = {
  迷茫:'迷茫', 疲憊:'疲憊', 委屈:'委屈', 憤怒:'憤怒',
  悲傷:'悲傷', 釋然:'釋然', 焦慮:'焦慮', 空洞:'空洞',
  自我懷疑:'自我懷疑', 平靜:'平靜',
};

/* ── 公開入口 ────────────────────────────────────────── */
export async function renderDashboard(container, weeklyData) {
  // 邊界條件：資料不足 → 降級留白充電卡
  const curve = weeklyData?.stats?.arousal_curve || [];
  if (!weeklyData || weeklyData.is_low_engagement || curve.length <= 1) {
    renderFallbackUI(container, weeklyData);
    return;
  }

  container.innerHTML = `
    <div class="space-y-4 animate-fade-in px-4 py-5">

      <!-- Stats -->
      <div class="grid grid-cols-3 gap-3">
        ${_statCard('情緒強度', weeklyData.stats?.avg_arousal?.toFixed(1) ?? '—', '/5')}
        ${_statCard('對話輪數', weeklyData.raw_count ?? '—', '輪')}
        ${_statCard('活躍天數', Object.keys(weeklyData.stats?.daily_counts || {}).length || '—', '天')}
      </div>

      <!-- 摘要 -->
      ${weeklyData.summary ? `
      <div class="bg-glow-card rounded-xl p-4 border border-slate-800/60">
        <p class="text-xs text-slate-500 uppercase tracking-widest mb-2">本週摘要</p>
        <p class="text-slate-200 text-sm leading-relaxed">${_esc(weeklyData.summary)}</p>
      </div>` : ''}

      <!-- 折線圖 -->
      <div class="p-4 bg-glow-card rounded-2xl border border-slate-800/80">
        <h4 class="text-xs font-semibold text-slate-400 mb-2">✦ 多週情緒起伏趨勢</h4>
        <div class="h-48"><canvas id="arousalChart"></canvas></div>
      </div>

      <!-- 橫向長條圖 -->
      <div class="p-4 bg-glow-card rounded-2xl border border-slate-800/80">
        <h4 class="text-xs font-semibold text-slate-400 mb-2">✦ 當週情緒分佈佔比</h4>
        <div class="h-40"><canvas id="emotionBarChart"></canvas></div>
      </div>

      <!-- 成長觀察 -->
      ${weeklyData.growth_note ? `
      <div class="flex gap-3 bg-emerald-950/40 rounded-xl p-4 border border-emerald-500/15">
        <span class="text-emerald-400 text-lg flex-shrink-0">🌱</span>
        <p class="text-emerald-300 text-sm italic leading-relaxed">${_esc(weeklyData.growth_note)}</p>
      </div>` : ''}

      <!-- 洞察名言卡 -->
      ${_insightCard(weeklyData.psych_context || {})}

    </div>`;

  let Chart;
  try {
    const chartModule = await import('https://cdn.jsdelivr.net/npm/chart.js@4.4.0/+esm');
    Chart = chartModule.Chart;
    Chart.register(...chartModule.registerables);
  } catch (e) {
    console.warn('[Dashboard] Chart.js 載入失敗:', e);
    return;
  }

  // 銷毀舊實例
  safelyDestroyChart('arousalChart');
  safelyDestroyChart('emotionBarChart');

  // 資料轉換：提取後端 [{t, v}] 格式中的 .v
  const labels        = curve.map(p => p.t || '');
  const currentValues = curve.map(p => p.v);

  // 上週基準疊圖防呆：
  //   有 past_baseline 且長度匹配 → 提取 .v
  //   無資料                       → 以本週平均填充虛線
  const avgCurrent = currentValues.reduce((a, b) => a + b, 0) / currentValues.length;
  const pb = weeklyData.stats.past_baseline;
  const baselineValues = (Array.isArray(pb) && pb.length === curve.length)
    ? pb.map(p => (typeof p === 'object' ? p.v : p))
    : new Array(curve.length).fill(+avgCurrent.toFixed(2));

  // 折線圖
  window.mindBotCharts['arousalChart'] = new Chart(
    document.getElementById('arousalChart'), {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label:           '本週喚醒度',
            data:            currentValues,
            borderColor:     '#6366f1',
            backgroundColor: 'rgba(99,102,241,.05)',
            borderWidth:     2,
            pointRadius:     3,
            tension:         .3,
            fill:            true,
          },
          {
            label:       '上週基準',
            data:        baselineValues,
            borderColor: '#475569',
            borderDash:  [4, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            tension:     .3,
            fill:        false,
          },
        ],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { min:1, max:5, grid:{ color:'rgba(255,255,255,.04)' }, ticks:{ color:'#475569', stepSize:1 } },
          x: { grid:{ display:false }, ticks:{ color:'#475569', font:{ size:10 } } },
        },
      },
    }
  );

  // 橫向長條圖（對齊後端欄位 emotion_counts）
  const emotionCounts = weeklyData.stats.emotion_counts || {};
  const emotionLabels = Object.keys(emotionCounts).map(k => EMOTION_LABEL[k] || k);
  const emotionValues = Object.values(emotionCounts);

  window.mindBotCharts['emotionBarChart'] = new Chart(
    document.getElementById('emotionBarChart'), {
      type: 'bar',
      data: {
        labels:   emotionLabels.length ? emotionLabels : ['平靜', '日常'],
        datasets: [{
          data:            emotionValues.length ? emotionValues : [1, 0],
          backgroundColor: emotionLabels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderRadius:    6,
        }],
      },
      options: {
        indexAxis:           'y',
        responsive:          true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid:{ color:'rgba(255,255,255,.04)' }, ticks:{ color:'#475569', precision:0 } },
          y: { grid:{ display:false }, ticks:{ color:'#94a3b8', font:{ size:11 } } },
        },
      },
    }
  );
}

/* ── 記憶體安全銷毀 ─────────────────────────────────── */
function safelyDestroyChart(canvasId) {
  if (window.mindBotCharts[canvasId]) {
    window.mindBotCharts[canvasId].destroy();
    delete window.mindBotCharts[canvasId];
  }
}

/* ── 降級留白充電 UI ────────────────────────────────── */
export function renderFallbackUI(container, weeklyData) {
  const pc      = weeklyData?.psych_context || {};
  const summary = weeklyData?.summary
    || '這週你選擇把心事暫時闔上，給了自己一段安靜沉澱的空間。不說話，也是一種對內心的溫柔傾聽。';
  const quote   = pc.end_quote    || '照顧好自己，不是自私，而是自我保護。';
  const author  = pc.quote_author || '奧黛麗・洛德';

  container.innerHTML = `
    <div class="animate-fade-in mx-4 my-6 p-6 rounded-2xl
                bg-gradient-to-br from-glow-main via-indigo-950 to-glow-main
                border border-indigo-500/20 shadow-2xl">
      <div class="flex items-center gap-3 mb-4">
        <div class="relative w-8 h-8 flex items-center justify-center flex-shrink-0">
          <span class="absolute animate-pulse-slow inline-flex h-full w-full
                       rounded-full bg-indigo-400 opacity-20"></span>
          <span class="text-2xl relative">🌙</span>
        </div>
        <div>
          <h3 class="text-base font-bold text-indigo-200 tracking-wide">本週的留白充電</h3>
          ${weeklyData?.week_id
            ? `<p class="text-xs text-slate-600 mt-0.5">${_esc(weeklyData.week_id)}</p>`
            : ''}
        </div>
      </div>
      <p class="text-slate-300 text-sm leading-relaxed mb-5">${_esc(summary)}</p>
      ${pc.tarot_name_zh ? `
      <div class="inline-flex items-center gap-1.5 text-xs text-amber-400
                  border border-amber-500/20 rounded-full px-3 py-1 mb-4">
        🔮 ${_esc(pc.tarot_name_zh)}
      </div>` : ''}
      ${pc.dialogue_insight ? `
      <p class="text-slate-500 text-xs italic leading-relaxed mb-4">
        ${_esc(pc.dialogue_insight)}
      </p>` : ''}
      <div class="border-t border-slate-800/80 pt-5">
        <p class="italic text-slate-400 text-sm leading-relaxed">「${_esc(quote)}」</p>
        <p class="text-right text-xs text-amber-400 font-medium mt-2">——&nbsp;${_esc(author)}</p>
      </div>

      <!-- 新手 CTA：引導去 LINE 開啟第一次對話 -->
      <button id="go-line-cta"
              class="mt-6 w-full py-3.5 rounded-2xl text-sm font-semibold
                     bg-gradient-to-r from-indigo-950/80 to-violet-950/60
                     border border-indigo-500/30 text-indigo-200
                     active:scale-95 transition-all">
        🪐 去 LINE 官方帳號開啟第一次對話
      </button>
    </div>`;

  // 按鈕：LINE 內關窗回聊天室，瀏覽器則開新頁
  requestAnimationFrame(() => {
    document.getElementById('go-line-cta')?.addEventListener('click', () => {
      if (window.liff?.isInClient()) {
        window.liff.closeWindow();
      } else {
        window.open('https://line.me/R/ti/p/@mindbot', '_blank');
      }
    });
  });
}

/* ── 洞察名言卡 ──────────────────────────────────────── */
function _insightCard(pc) {
  if (!pc.dialogue_insight && !pc.end_quote) return '';
  return `
    <div class="bg-glow-card rounded-xl p-4 border-l-2 border-amber-500/40">
      ${pc.dialogue_insight
        ? `<p class="text-slate-300 text-sm leading-relaxed mb-3">${_esc(pc.dialogue_insight)}</p>
           <hr class="border-white/5 mb-3">`
        : ''}
      ${pc.end_quote
        ? `<p class="italic text-slate-400 text-sm leading-relaxed">「${_esc(pc.end_quote)}」</p>
           <p class="text-right text-xs text-amber-400 mt-2">——&nbsp;${_esc(pc.quote_author || '')}</p>`
        : ''}
    </div>`;
}

function _statCard(label, val, unit) {
  return `
    <div class="bg-glow-card rounded-xl p-3 text-center border border-slate-800/60">
      <div class="text-2xl font-light text-amber-300">
        ${val}<span class="text-xs text-slate-500 ml-0.5">${unit}</span>
      </div>
      <div class="text-xs text-slate-500 mt-1 tracking-wide">${label}</div>
    </div>`;
}

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
