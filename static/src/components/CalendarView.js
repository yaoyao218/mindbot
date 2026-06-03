/**
 * CalendarView.js — 金色✦情緒月曆
 *
 * 規格書實作：
 * - 日期格子帶 data-date 與 data-empty 屬性
 * - 全域點擊委派由 app.js 在 #app-runtime 統一監聽（不在此元件內綁定）
 * - dayData 為 null 時安全代入 dateStr，data-empty="true"，
 *   絕不傳入 undefined 給 Modal
 */

/**
 * @param {HTMLElement} container
 * @param {number}      year
 * @param {number}      month   1-indexed
 * @param {Object[]}    records - emotion_calendar 陣列
 */
export function renderCalendar(container, year, month, records = []) {
  const recordMap = {};
  records.forEach(r => { if (r.record_date) recordMap[r.record_date] = r; });

  const firstDay = new Date(year, month - 1, 1).getDay(); // 0=Sun
  const daysInMo = new Date(year, month, 0).getDate();
  const today    = new Date().toISOString().slice(0, 10);

  const monthLabel = new Date(year, month - 1, 1)
    .toLocaleDateString('zh-Hant', { year: 'numeric', month: 'long' });

  container.innerHTML = `
    <div class="animate-fade-in px-4 py-5">

      <!-- 月份標題 + 切換 -->
      <div class="flex items-center justify-between mb-4">
        <button data-cal="prev"
                class="w-9 h-9 rounded-full bg-glow-card border border-white/8
                       text-slate-400 flex items-center justify-center
                       active:scale-90 transition text-lg">‹</button>
        <h2 class="text-glow-text font-semibold tracking-wide text-sm">${monthLabel}</h2>
        <button data-cal="next"
                class="w-9 h-9 rounded-full bg-glow-card border border-white/8
                       text-slate-400 flex items-center justify-center
                       active:scale-90 transition text-lg">›</button>
      </div>

      <!-- 週標題 -->
      <div class="grid grid-cols-7 gap-1 mb-1">
        ${['日','一','二','三','四','五','六'].map(d =>
          `<div class="text-center text-xs text-slate-600 py-1">${d}</div>`
        ).join('')}
      </div>

      <!-- 日期格子（data-date / data-empty 屬性）-->
      <div class="grid grid-cols-7 gap-1">
        ${_buildCells(year, month, firstDay, daysInMo, recordMap, today)}
      </div>

      <!-- 圖例 -->
      <div class="flex items-center gap-2 mt-4 justify-end">
        <span class="text-amber-400 font-bold text-xs">✦</span>
        <span class="text-xs text-slate-500">有塔羅紀錄</span>
      </div>
    </div>`;

  // 月份切換按鈕（分派 month-change 事件給 app.js 監聽）
  container.querySelector('[data-cal="prev"]')?.addEventListener('click', () => {
    const d = new Date(year, month - 2, 1);
    container.dispatchEvent(new CustomEvent('month-change', {
      detail: { year: d.getFullYear(), month: d.getMonth() + 1 }, bubbles: true,
    }));
  });
  container.querySelector('[data-cal="next"]')?.addEventListener('click', () => {
    const d = new Date(year, month, 1);
    container.dispatchEvent(new CustomEvent('month-change', {
      detail: { year: d.getFullYear(), month: d.getMonth() + 1 }, bubbles: true,
    }));
  });
}

function _buildCells(year, month, firstDay, daysInMo, recordMap, today) {
  const cells = [];

  // 起始空白格
  for (let i = 0; i < firstDay; i++) {
    cells.push('<div class="h-14"></div>');
  }

  for (let d = 1; d <= daysInMo; d++) {
    const mm      = String(month).padStart(2, '0');
    const dd      = String(d).padStart(2, '0');
    const dateStr = `${year}-${mm}-${dd}`;
    const data    = recordMap[dateStr] || null;
    cells.push(generateDayCell(d, data, dateStr, today));
  }

  return cells.join('');
}

/**
 * 單日格子
 * 規格書：data-date 必須是 YYYY-MM-DD，data-empty="true" 代表無資料
 */
export function generateDayCell(day, dayData, dateStr, today = '') {
  const hasTarot   = !!dayData?.tarot_card;
  const isEmpty    = !dayData;
  const isToday    = dateStr === today;

  const tarotClass = hasTarot ? 'has-tarot' : '';
  const todayRing  = isToday  ? 'ring-2 ring-indigo-500/60' : '';
  const dimmed     = isEmpty  ? 'opacity-50' : '';

  return `
    <div class="relative h-14 rounded-lg flex flex-col items-center justify-between p-1
                bg-slate-900/50 border border-slate-800/50
                hover:border-indigo-500/30 active:scale-95
                cursor-pointer transition ${tarotClass} ${todayRing} ${dimmed}"
         data-date="${dateStr}"
         data-empty="${isEmpty}">
      <span class="text-xs text-slate-500 self-start leading-none">${day}</span>
      <span class="text-xl mb-0.5">${dayData?.emotion_emoji || ''}</span>
    </div>`;
}
