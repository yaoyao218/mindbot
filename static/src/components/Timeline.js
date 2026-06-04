/**
 * Timeline.js — 雙欄沉浸式時光機對話留存
 *
 * 佈局：左 7/10 莫蘭迪氣泡對話區 ｜ 右 3/10 潛意識氣泡看板（md+ 顯示）
 * 氣泡：user → 煙燻藍毛玻璃靠右 ｜ bot → 深灰毛玻璃靠左 + 臨床標籤
 * 防衛：基於相鄰 user 訊息內容推斷，bot 氣泡背景微染對應色調
 * 塔羅坑：最後一則 user 訊息觸發 STAGNANT 時自動掛載 3D 翻牌
 * PsychBubble：右側常駐 live-psych-canvas，使用 snapData.triad 驅動
 */

import { db, getSetting, setSetting } from '../db.js';

const PAGE_SIZE = 20;
let _page = 0;

// ── 防衛機制規則（內容關鍵字推斷）───────────────────────
const DEFENSE_RULES = [
  {
    patterns: ['都是','他','主管','公司','幹嘛','死開','隨便','不公平',
               '憑什麼','爛','破','針對','這個環境','他們','怪別人'],
    label:  '臨床看見：外在化憤怒承接',
    bg:     'rgba(195,175,145,.08)',
    border: 'rgba(195,175,145,.18)',
    chip:   'rgba(205,185,155,.65)',
  },
  {
    patterns: ['理性上','從邏輯','客觀','心理學','認知','其實只是',
               '就是因為','本質上','分析','所謂','這不過是'],
    label:  '臨床看見：理智化隔離防衛',
    bg:     'rgba(140,160,180,.08)',
    border: 'rgba(140,160,180,.18)',
    chip:   'rgba(150,170,190,.65)',
  },
];

// ── STAGNANT 觸發關鍵字 ──────────────────────────────────
const STAGNANT_PATTERNS = [
  '隨便','死開','算了','不想說','你根本不懂','廢話',
  '沒用','隨便你','幹嘛問','不想談','無所謂','隨便啦',
];

// ── 公開入口 ─────────────────────────────────────────────
export async function renderTimeline(container, snapData) {
  _page = 0;

  // 銷毀舊 Observer + PsychBubble
  if (window.mindBotObserver) {
    window.mindBotObserver.disconnect();
    window.mindBotObserver = null;
  }
  window._mbPsychBubble?.destroy();
  window._mbPsychBubble = null;

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

  // ── 雙欄佈局骨架 ────────────────────────────────────────
  container.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-10 h-[calc(100vh-140px)] overflow-hidden">

      <!-- ▌左側 7/10：莫蘭迪對話留存 -->
      <div class="col-span-1 md:col-span-7 overflow-y-auto" id="timeline-scroll">
        <div class="px-4 pt-5 pb-28">

          <!-- 區塊標題 -->
          <div class="flex items-center gap-2 mb-5">
            <span style="font-size:9px;letter-spacing:.18em;color:rgba(99,102,241,.4);
                         text-transform:uppercase;font-weight:500">✦ 時光機對話留存</span>
            <div style="flex:1;height:1px;background:rgba(99,102,241,.06)"></div>
          </div>

          <!-- 氣泡列表 -->
          <div id="timeline-list" class="space-y-3"></div>

          <!-- IntersectionObserver 哨兵 -->
          <div id="timeline-sentinel"
               class="h-14 flex items-center justify-center">
            <span class="animate-pulse" style="font-size:11px;color:#1e293b">讀取中…</span>
          </div>
        </div>
      </div>

      <!-- ▌右側 3/10：潛意識氣泡看板（僅 md+ 顯示）-->
      <div id="subconscious-panel"
           class="hidden md:flex flex-col"
           style="background:rgba(7,11,20,.78);
                  backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
                  border-left:1px solid rgba(99,102,241,.07)">

        <!-- 看板標題 -->
        <div class="px-4 pt-4 pb-2 flex-shrink-0">
          <p style="font-size:9px;letter-spacing:.18em;
                    color:rgba(99,102,241,.4);text-transform:uppercase">
            潛意識生態系
          </p>
          <p style="font-size:10px;color:#1e293b;margin-top:3px">心理模式即時流體圖</p>
        </div>

        <!-- Canvas 佔位 -->
        <div class="flex-1 relative min-h-0" id="psych-canvas-wrap">
          <canvas id="live-psych-canvas"
                  style="position:absolute;inset:0;width:100%;height:100%;
                         display:block"></canvas>

          <!-- 空態：無 triad 資料時顯示 -->
          <div id="psych-empty-hint"
               style="position:absolute;inset:0;display:flex;flex-direction:column;
                      align-items:center;justify-content:center;padding:24px;
                      text-align:center;pointer-events:none">
            <span style="font-size:2.5rem;opacity:.12;margin-bottom:14px">🌊</span>
            <p style="color:#1e293b;font-size:11px;line-height:1.7">
              完成一次深度對話後，<br>心理模式氣泡將<br>在此漂浮呼吸
            </p>
          </div>
        </div>

        <!-- 底部：週期標籤 -->
        <div class="px-3 py-2 flex-shrink-0"
             style="border-top:1px solid rgba(15,23,42,.9)">
          <p id="psych-panel-week"
             style="font-size:9px;color:#1e293b;text-align:center;letter-spacing:.1em">
          </p>
        </div>
      </div>
    </div>`;

  const listEl   = document.getElementById('timeline-list');
  const sentinel = document.getElementById('timeline-sentinel');
  if (!listEl || !sentinel) return;

  // 首次載入
  await _loadNextPage(listEl, sentinel);

  // 設置 IntersectionObserver
  window.mindBotObserver = new IntersectionObserver(
    async (entries) => {
      if (entries[0].isIntersecting) await _loadNextPage(listEl, sentinel);
    },
    { root: null, rootMargin: '100px' }
  );
  window.mindBotObserver.observe(sentinel);

  // 掛載 PsychBubble（有 triad 才顯示，無資料保留空態提示）
  _mountLivePsychBubble(snapData);
}

// ── 分頁載入 ────────────────────────────────────────────────
async function _loadNextPage(listEl, sentinel) {
  const msgs = await db.conversations
    .orderBy('id')
    .reverse()
    .offset(_page * PAGE_SIZE)
    .limit(PAGE_SIZE)
    .toArray();

  if (!msgs.length) {
    sentinel.innerHTML =
      '<span style="font-size:11px;color:#1e293b">— 已顯示所有心事對話 —</span>';
    window.mindBotObserver?.disconnect();
    return;
  }

  const sorted   = msgs.reverse();
  const fragment = document.createDocumentFragment();

  sorted.forEach((msg, i) => {
    const prev = i > 0 ? sorted[i - 1] : null;
    fragment.appendChild(_buildBubble(msg, prev));
  });

  // ── STAGNANT 塔羅坑（只在第一頁末尾判斷）──────────────
  if (_page === 0) {
    const lastUser = [...sorted].reverse().find(m => m.role === 'user');
    if (lastUser && _isStagnant(lastUser.content || '')) {
      fragment.appendChild(_buildTarotDock());
    }
  }

  listEl.appendChild(fragment);
  _page++;
  sentinel.innerHTML =
    '<span class="animate-pulse" style="font-size:11px;color:#1e293b">繼續載入…</span>';
}

// ── 莫蘭迪氣泡 ─────────────────────────────────────────────
function _buildBubble(msg, prevMsg) {
  const wrap    = document.createElement('div');
  const timeStr = new Date(msg.timestamp || 0)
    .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const content = _esc(msg.content || '');
  const isUser  = msg.role === 'user';

  if (isUser) {
    // 用戶氣泡：右對齊，煙燻藍毛玻璃
    wrap.className = 'flex justify-end';
    wrap.innerHTML = `
      <div style="max-width:72%;
                  background:rgba(124,154,181,.14);
                  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
                  border:1px solid rgba(124,154,181,.22);
                  border-radius:18px 18px 4px 18px;
                  padding:10px 14px">
        <p style="font-size:13px;color:#cbd5e1;line-height:1.65">${content}</p>
        <span style="font-size:10px;color:#334155;display:block;
                     text-align:right;margin-top:4px">${timeStr}</span>
      </div>`;
  } else {
    // AI 氣泡：左對齊，深灰毛玻璃 + 防衛色調 + 臨床標籤
    const defense = _detectDefense(prevMsg?.content || '');

    const bubbleBg = defense
      ? `background:${defense.bg};border:1px solid ${defense.border}`
      : 'background:rgba(14,21,32,.65);border:1px solid rgba(99,102,241,.09)';

    const defenseChip = defense ? `
      <div style="display:inline-block;margin-bottom:5px;
                  padding:2px 10px;border-radius:20px;
                  border:1px solid ${defense.chip};
                  font-family:'Noto Serif TC',Georgia,serif;
                  font-size:9px;letter-spacing:.06em;color:${defense.chip}">
        [ ${defense.label} ]
      </div><br>` : '';

    wrap.className = 'flex justify-start';
    wrap.innerHTML = `
      <div style="max-width:82%;
                  ${bubbleBg};
                  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
                  border-radius:18px 18px 18px 4px;
                  padding:10px 14px">
        <div style="font-family:'Noto Serif TC',Georgia,serif;
                    font-size:9px;letter-spacing:.08em;
                    color:rgba(99,102,241,.38);margin-bottom:5px">
          [ 系統動態：進入情感共鳴 Rapport 模式 ]
        </div>
        ${defenseChip}
        <p style="font-size:13px;color:#94a3b8;line-height:1.65">${content}</p>
        <span style="font-size:10px;color:#1e293b;display:block;
                     text-align:right;margin-top:4px">${timeStr}</span>
      </div>`;
  }

  return wrap;
}

// ── 防衛機制偵測 ────────────────────────────────────────────
function _detectDefense(userText) {
  if (!userText) return null;
  const t = userText;
  for (const rule of DEFENSE_RULES) {
    if (rule.patterns.some(p => t.includes(p))) return rule;
  }
  return null;
}

// ── STAGNANT 偵測 ───────────────────────────────────────────
function _isStagnant(text) {
  return STAGNANT_PATTERNS.some(p => text.includes(p));
}

// ── STAGNANT 塔羅坑 ─────────────────────────────────────────
function _buildTarotDock() {
  const dock = document.createElement('div');
  dock.id = 'stagnant-tarot-dock';
  dock.style.cssText = 'margin:20px 0 4px';

  // 標題
  const label = document.createElement('p');
  label.style.cssText =
    'font-size:9px;letter-spacing:.14em;color:rgba(245,158,11,.4);' +
    'text-transform:uppercase;margin-bottom:8px;text-align:center';
  label.textContent = '✦ AI 偵測到停滯信號，為你投影一張牌';
  dock.appendChild(label);

  // 動態 import TarotFlip 並掛載
  import('./tarot_flip.js')
    .then(({ renderTarotFlip }) => {
      if (!dock.isConnected) return;
      renderTarotFlip(dock, {
        card_name:           '停滯之鏡',
        meaning:             '此刻的阻抗，正是內心在保護某個還來不及說出口的脆弱部分。',
        projective_question: '在這份「隨便」或「死開」之下，有一個你還不敢承認的真實感受，它會是什麼？',
      });
    })
    .catch(() => {});

  return dock;
}

// ── PsychBubble 掛載到右側常駐 Canvas ─────────────────────
async function _mountLivePsychBubble(snapData) {
  const canvas = document.getElementById('live-psych-canvas');
  if (!canvas) return;

  const triad   = snapData?.triad;
  const hasData = (triad?.emotion?.length || 0)
                + (triad?.cognition?.length || 0)
                + (triad?.need?.length || 0) > 0;

  if (!hasData) return;   // 保留空態提示

  const hint = document.getElementById('psych-empty-hint');
  if (hint) hint.style.display = 'none';

  const footer = document.getElementById('psych-panel-week');
  if (footer && snapData?.week_id) footer.textContent = snapData.week_id;

  try {
    const { PsychBubble } = await import('./psych_bubble.js');
    if (!canvas.isConnected) return;
    // 確保舊實例已清除，才建立新的
    window._mbPsychBubble?.destroy();
    window._mbPsychBubble = new PsychBubble(canvas, triad);
  } catch (e) {
    console.warn('[Timeline] PsychBubble 載入失敗:', e);
  }
}

// ── 備份開關：Transaction 物理銷毀 ──────────────────────────
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
