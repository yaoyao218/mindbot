/**
 * Dashboard.js — 雙模態沉澱快照 + 情感考古卡片
 *
 * 記憶體防禦：
 *   window.mindBotCharts（Key = Canvas ID）→ safelyDestroyChart()
 *   window._mbPsychBubble                  → 路由切換前呼叫 destroy()
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

      <!-- 心靈投射牌掛載點（_renderWeeklyTarotDock 動態填入）-->
      <div id="weekly-tarot-mount"></div>

      <!-- 考古卡片掛載點（renderArchaeologyCard 動態填入）-->
      <div id="arch-mount"></div>

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

  // 心靈投射牌（有無塔羅資料皆渲染；無資料時改用週度大阿爾克那）
  const tarotMount = document.getElementById('weekly-tarot-mount');
  if (tarotMount) _renderWeeklyTarotDock(tarotMount, weeklyData.psych_context || {}, weeklyData.week_id).catch(() => {});

  // 考古卡片（有 archaeology / triad 才渲染，無資料時靜默跳過）
  const archMount = document.getElementById('arch-mount');
  if (archMount) renderArchaeologyCard(archMount, weeklyData).catch(() => {});
}

/* ── 記憶體安全銷毀 ─────────────────────────────────── */
function safelyDestroyChart(canvasId) {
  if (window.mindBotCharts[canvasId]) {
    window.mindBotCharts[canvasId].destroy();
    delete window.mindBotCharts[canvasId];
  }
}

/* ── 情感考古卡片 ────────────────────────────────────── */
async function renderArchaeologyCard(mount, data) {
  const tpl = document.getElementById('tpl-archaeology');
  if (!tpl) return;

  // 有任何考古欄位才渲染（snapshot 初期可能只有 summary/stats）
  const arch  = data.archaeology  || {};
  const arc   = data.narrative_arc || {};
  const triad = data.triad         || {};
  const hasArch  = arch.surface || arch.middle || arch.deep;
  const hasTriad = (triad.emotion?.length || 0)
                 + (triad.cognition?.length || 0)
                 + (triad.need?.length || 0) > 0;
  if (!hasArch && !hasTriad) return;

  // 銷毀上一個 Bubble 實例
  window._mbPsychBubble?.destroy();
  window._mbPsychBubble = null;

  // Clone template
  const fragment = tpl.content.cloneNode(true);
  const card     = fragment.querySelector('.arch-card');
  if (!card) return;

  // ── 資料填充工具 ─────────────────────────────────────
  const _set = (selector, text) => {
    card.querySelectorAll(selector).forEach(el => {
      el.textContent = text ?? '';
    });
  };
  const _show = (attr, cond) => {
    card.querySelectorAll(`[data-show="${attr}"]`).forEach(el => {
      el.style.display = cond ? '' : 'none';
    });
  };

  // 簡單文字欄位（data-bind）
  _set('[data-bind="week_id"]',    data.week_id);
  _set('[data-bind="summary"]',    data.summary);
  _set('[data-bind="growth_note"]', data.growth_note);
  _set('[data-bind="end_quote"]',  data.end_quote || data.psych_context?.end_quote);
  _set('[data-bind="quote_author"]',
    data.quote_author || data.psych_context?.quote_author || '');

  // 三層地質
  _set('[data-bind="archaeology.surface"]', arch.surface);
  _set('[data-bind="archaeology.middle"]',  arch.middle);
  _set('[data-bind="archaeology.deep"]',    arch.deep);

  // 起承轉合
  _set('[data-bind="narrative_arc.opening"]',     arc.opening);
  _set('[data-bind="narrative_arc.development"]', arc.development);
  _set('[data-bind="narrative_arc.turning"]',     arc.turning);
  _set('[data-bind="narrative_arc.closing"]',     arc.closing);

  // 主題標籤（動態生成 .arch-theme-tag span）
  const themesEl = card.querySelector('[data-bind="themes"]');
  if (themesEl) {
    themesEl.innerHTML = (data.themes || [])
      .map(t => `<span class="arch-theme-tag">${_esc(t)}</span>`)
      .join('');
  }

  // 條件顯示
  _show('growth_note', data.growth_note);
  _show('end_quote',   data.end_quote || data.psych_context?.end_quote);

  // 三層地質整區：surface 都空則隱藏
  if (!hasArch) {
    card.querySelector('.arch-layers')?.remove();
  }

  // 起承轉合整區：全空則隱藏
  if (!arc.opening && !arc.development && !arc.turning && !arc.closing) {
    card.querySelector('.arch-narrative')?.remove();
  }

  // 掛載 DOM（先 append，canvas 才有尺寸）
  mount.appendChild(fragment);

  // ── PsychBubble（動態 import，避免影響首屏載入）────
  if (hasTriad) {
    try {
      const { PsychBubble } = await import('./psych_bubble.js');

      // ── 競態守衛：await 期間用戶可能已切換路由 ──
      if (!mount.isConnected) return;

      const canvas = mount.querySelector('.arch-bubble-wrap canvas');
      if (canvas) {
        // 再次銷毀任何在 await 期間被建立的孤兒實例
        window._mbPsychBubble?.destroy();
        window._mbPsychBubble = new PsychBubble(canvas, triad);
      }
    } catch (e) {
      console.warn('[Dashboard] PsychBubble 載入失敗:', e);
      mount.querySelector('.arch-bubble-wrap')?.remove();
      mount.querySelector('.arch-bubble-label')?.remove();
    }
  } else {
    mount.querySelector('.arch-bubble-wrap')?.remove();
    mount.querySelector('.arch-bubble-label')?.remove();
  }
}

/* ── 大阿爾克那牌池（週度心靈大局基調）────────────────
 *  當用戶尚未觸發收尾塔羅時，依週別輪換一張大阿爾克那
 *  作為潛意識背景提示，維持儀式感。
 */
const _MAJOR_ARCANA_POOL = [
  { card_name: '隱者',   meaning: '此刻需要向內探索，外界的喧囂可以先放下。答案往往在安靜之中浮現。',   is_reversed: false },
  { card_name: '月亮',   meaning: '潛意識的波濤正在湧現，夢境與直覺比理性更接近真相。',                  is_reversed: false },
  { card_name: '星星',   meaning: '療癒正在悄悄進行，信任這個看不見結果的過程。',                        is_reversed: false },
  { card_name: '力量',   meaning: '溫柔地面對自己，比強迫自己振作更需要勇氣。',                          is_reversed: false },
  { card_name: '愚者',   meaning: '新的開始正在醞釀，此刻的未知是機遇的伏筆。',                          is_reversed: false },
  { card_name: '審判',   meaning: '過去的一切正在召喚你誠實地面對，這是覺醒的開端。',                    is_reversed: false },
  { card_name: '戰車',   meaning: '內在的衝突需要整合，找到前進的方向比速度更重要。',                    is_reversed: false },
];

async function _renderWeeklyTarotDock(mount, pc, weekId) {
  if (!mount.isConnected) return;

  const { renderTarotFlip } = await import('./tarot_flip.js');
  if (!mount.isConnected) return;

  // 有真實觸發牌 → 直接呈現
  const hasRealCard = !!(pc.tarot_card || pc.tarot_name_zh);

  let cardData;
  if (hasRealCard) {
    cardData = {
      card_name:           pc.tarot_name_zh || pc.tarot_card,
      meaning:             pc.tarot_meaning  || pc.dialogue_insight || '',
      is_reversed:         pc.tarot_reversed || false,
      defense_type:        pc.defense_type   || '',
      projective_question: pc.projective_question || '',
    };
  } else {
    // 無觸發牌 → 依週別 hash 選一張大阿爾克那
    const seed = weekId
      ? weekId.replace(/\D/g, '').split('').reduce((a, c) => a + +c, 0)
      : new Date().getDay();
    cardData = _MAJOR_ARCANA_POOL[seed % _MAJOR_ARCANA_POOL.length];
  }

  // 外層容器
  mount.innerHTML = `
    <div>
      <p style="font-size:10px;letter-spacing:.16em;
                color:rgba(245,158,11,.55);text-transform:uppercase;
                margin-bottom:8px;padding:0 4px">
        ✦ ${hasRealCard ? '本週心靈投射牌' : '當前心靈大局概況'}
      </p>
      <div id="wt-flip-inner"></div>
    </div>`;

  const inner = mount.querySelector('#wt-flip-inner');
  if (inner) renderTarotFlip(inner, cardData);
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
        const id = window.MindBotApp?._lineAccountId;
        window.open(id ? `https://line.me/R/ti/p/${id}` : 'https://line.me/', '_blank');
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
