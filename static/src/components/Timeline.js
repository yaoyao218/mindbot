/**
 * Timeline.js — 時光機對話留存
 *
 * 效能設計：IntersectionObserver 分頁懶載入
 *   - 每頁 20 則（PAGE_SIZE）
 *   - 哨兵節點 #timeline-sentinel → 觸發下一頁
 *   - rootMargin: '100px' → 提前 100px 預載
 *   - DocumentFragment 批次插入 → 單次 Reflow
 *
 * 記憶體根治：
 *   使用 window.mindBotObserver（全域命名）
 *   路由切換時 disconnect() + null，防止殘留監聽洩漏
 *
 * 隱私設計：
 *   toggleLocalBackup(false) → db.transaction 原子清空
 */

import { db, getSetting, setSetting } from '../db.js';

let currentPage = 0;
const PAGE_SIZE = 20;

/* ── 公開入口 ────────────────────────────────────────── */
export async function renderTimeline(container) {
  currentPage = 0;

  // 路由切換時實體銷毀舊 Observer，根治記憶體洩漏
  if (window.mindBotObserver) {
    window.mindBotObserver.disconnect();
    window.mindBotObserver = null;
  }

  const keepLocal = await getSetting('keep_local_history', true);
  if (!keepLocal) {
    container.innerHTML = `
      <div class="flex flex-col items-center justify-center py-16 text-center px-6">
        <span class="text-4xl mb-4">🔒</span>
        <p class="text-slate-400 text-sm">本地日記備份未開啟</p>
        <p class="text-slate-600 text-xs mt-2 leading-relaxed">
          在「設定」頁面開啟後，<br>未來的對話將保存在本裝置中
        </p>
        <button onclick="window.MindBotApp.navigate('#settings')"
                class="mt-5 px-5 py-2 rounded-xl bg-indigo-950/60 border border-indigo-500/20
                       text-indigo-300 text-xs font-medium active:scale-95 transition">
          前往設定
        </button>
      </div>`;
    return;
  }

  container.innerHTML = `
    <div class="p-4 space-y-4">
      <h3 class="text-sm font-bold text-indigo-300 tracking-wider">時光機對話留存</h3>
      <div id="timeline-list" class="space-y-3"></div>
      <div id="timeline-sentinel"
           class="h-12 flex items-center justify-center text-xs text-slate-500">
        <span class="animate-pulse">讀取中...</span>
      </div>
    </div>`;

  const listContainer = document.getElementById('timeline-list');
  const sentinel      = document.getElementById('timeline-sentinel');
  if (!listContainer || !sentinel) return;

  // 首次主動載入
  await _loadNextPage(listContainer, sentinel);

  // 建立邊界監聽器（全域命名）
  window.mindBotObserver = new IntersectionObserver(
    async (entries) => {
      if (entries[0].isIntersecting) {
        await _loadNextPage(listContainer, sentinel);
      }
    },
    { root: null, rootMargin: '100px' }
  );
  window.mindBotObserver.observe(sentinel);
}

/* ── 分頁載入（Dexie 原生游標，絕不全量陣列）──────────── */
async function _loadNextPage(listContainer, sentinel) {
  // 利用 Dexie 原生 offset/limit 做高效分頁
  const messages = await db.conversations
    .orderBy('id')
    .reverse()
    .offset(currentPage * PAGE_SIZE)
    .limit(PAGE_SIZE)
    .toArray();

  if (!messages.length) {
    sentinel.textContent = '— 已顯示所有心事對話 —';
    if (window.mindBotObserver) window.mindBotObserver.disconnect();
    return;
  }

  // 倒序 → 時間由舊到新顯示
  const sorted = messages.reverse();

  // DocumentFragment 批次插入 → 將瀏覽器 Reflow/Repaint 壓縮至單次
  const fragment = document.createDocumentFragment();

  sorted.forEach(msg => {
    const msgEl      = document.createElement('div');
    const timeStr    = new Date(msg.timestamp || 0)
      .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    msgEl.className = `p-3 rounded-xl max-w-[85%] text-xs leading-relaxed ${
      msg.role === 'user'
        ? 'bg-indigo-600/90 text-white ml-auto rounded-br-none'
        : 'bg-glow-card text-slate-200 border border-slate-800/60 rounded-bl-none'
    }`;
    msgEl.innerHTML = `
      <p>${_esc(msg.content || '')}</p>
      <span class="text-[10px] text-slate-400 block mt-1 text-right">${timeStr}</span>`;

    fragment.appendChild(msgEl);
  });

  listContainer.appendChild(fragment);
  currentPage++;
  sentinel.innerHTML = '<span class="animate-pulse">繼續載入…</span>';
}

/* ── 備份開關：Transaction 物理銷毀 ─────────────────── */
/**
 * @param {boolean} isEnabled
 * @returns {Promise<boolean>}  true = 開啟；false = 已物理銷毀
 */
export async function toggleLocalBackup(isEnabled) {
  await setSetting('keep_local_history', isEnabled);
  if (!isEnabled) {
    await db.transaction('rw', db.conversations, async () => {
      await db.conversations.clear();
    });
    return false;
  }
  return true;
}

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
