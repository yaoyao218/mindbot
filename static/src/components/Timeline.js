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
        <div class="px-5 md:px-8 pt-6 pb-32">

          <!-- 區塊標題 -->
          <div class="flex items-center gap-3 mb-6">
            <span style="font-size:10px;letter-spacing:.18em;color:rgba(99,102,241,.6);
                         text-transform:uppercase;font-weight:600">✦ 時光機對話留存</span>
            <div style="flex:1;height:1px;background:rgba(99,102,241,.1)"></div>
          </div>

          <!-- 氣泡列表 -->
          <div id="timeline-list" class="space-y-4"></div>

          <!-- IntersectionObserver 哨兵 -->
          <div id="timeline-sentinel"
               class="h-14 flex items-center justify-center">
            <span class="animate-pulse" style="font-size:12px;color:#334155">讀取中…</span>
          </div>
        </div>
      </div>

      <!-- ▌右側 3/10：潛意識氣泡看板（僅 md+ 顯示）-->
      <div id="subconscious-panel"
           class="hidden md:flex flex-col"
           style="background:rgba(7,11,20,.82);
                  backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
                  border-left:1px solid rgba(99,102,241,.12)">

        <!-- 看板標題 -->
        <div class="px-5 pt-5 pb-3 flex-shrink-0">
          <p style="font-size:10px;letter-spacing:.18em;
                    color:rgba(99,102,241,.65);text-transform:uppercase;font-weight:600">
            潛意識生態系
          </p>
          <p style="font-size:11px;color:#475569;margin-top:4px">心理模式即時流體圖</p>
        </div>

        <!-- Canvas 佔位 -->
        <div class="flex-1 relative min-h-0" id="psych-canvas-wrap">
          <canvas id="live-psych-canvas"
                  style="position:absolute;inset:0;width:100%;height:100%;
                         display:block"></canvas>

          <!-- 空態：無 triad 資料時顯示 -->
          <div id="psych-empty-hint"
               style="position:absolute;inset:0;display:flex;flex-direction:column;
                      align-items:center;justify-content:center;padding:28px;
                      text-align:center;pointer-events:none">
            <span style="font-size:2.5rem;opacity:.18;margin-bottom:16px">🌊</span>
            <p style="color:#475569;font-size:12px;line-height:1.8">
              完成一次深度對話後，<br>心理模式氣泡將<br>在此漂浮呼吸
            </p>
          </div>
        </div>

        <!-- 底部：週期標籤 -->
        <div class="px-4 py-3 flex-shrink-0"
             style="border-top:1px solid rgba(30,41,59,.8)">
          <p id="psych-panel-week"
             style="font-size:10px;color:#475569;text-align:center;letter-spacing:.1em">
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
      <div style="max-width:75%;
                  background:rgba(124,154,181,.18);
                  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
                  border:1px solid rgba(124,154,181,.28);
                  border-radius:18px 18px 4px 18px;
                  padding:12px 16px">
        <p style="font-size:15px;color:rgba(255,255,255,.88);line-height:1.7">${content}</p>
        <span style="font-size:10px;color:#475569;display:block;
                     text-align:right;margin-top:5px">${timeStr}</span>
      </div>`;
  } else {
    // AI 氣泡：左對齊，深灰毛玻璃 + 防衛色調 + 臨床標籤
    const defense = _detectDefense(prevMsg?.content || '');

    const bubbleBg = defense
      ? `background:${defense.bg};border:1px solid ${defense.border}`
      : 'background:rgba(14,21,32,.8);border:1px solid rgba(99,102,241,.14)';

    // 防衛標籤：提高對比度（chip 顏色基礎不變，但確保可讀）
    const defenseChip = defense ? `
      <div style="display:inline-block;margin-bottom:7px;
                  padding:3px 12px;border-radius:20px;
                  background:rgba(0,0,0,.25);
                  border:1px solid ${defense.chip};
                  font-family:'Noto Serif TC',Georgia,serif;
                  font-size:10px;letter-spacing:.06em;color:${defense.chip}">
        ${defense.label}
      </div><br>` : '';

    wrap.className = 'flex justify-start';
    wrap.innerHTML = `
      <div style="max-width:82%;
                  ${bubbleBg};
                  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
                  border-radius:18px 18px 18px 4px;
                  padding:12px 16px">
        <div style="font-family:'Noto Serif TC',Georgia,serif;
                    font-size:10px;letter-spacing:.08em;
                    color:rgba(99,102,241,.65);margin-bottom:6px">
          ✦ 情感共鳴模式
        </div>
        ${defenseChip}
        <p style="font-size:15px;color:#cbd5e1;line-height:1.72">${content}</p>
        <span style="font-size:10px;color:#475569;display:block;
                     text-align:right;margin-top:5px">${timeStr}</span>
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

// ── 小阿爾克那牌池（停滯攔截專用 — 對應當下微觀防禦情緒）──
// 選取四花色中最能反映「停滯 / 阻抗 / 保護」能量的牌組
const _STAGNANT_MINOR_POOL = [
  // 寶劍（思維困住 / 迴避）
  { card_name: '寶劍四', meaning: '你需要停下來，不是因為你輸了，而是因為你的系統需要重啟。',
    projective_question: '如果暫時不想說，有沒有一件很小的事，是你願意先分享的？', is_reversed: false },
  { card_name: '寶劍八', meaning: '你覺得被困住，但那些限制有多少是真實的，有多少是你給自己的？',
    projective_question: '這份「不想說」的底下，是什麼讓你覺得說了也沒用？', is_reversed: false },
  { card_name: '寶劍九', meaning: '腦袋在運轉，反覆想著那些最壞的可能性。那個焦慮，需要被聽見，不是被解決。',
    projective_question: '現在最讓你感到窒息的一個念頭，是什麼？', is_reversed: false },
  // 聖杯（情感關閉 / 撤退）
  { card_name: '聖杯四', meaning: '你現在對很多事提不起勁。這不一定是問題，有時候是你需要向內看的訊號。',
    projective_question: '你最近是否有什麼感覺，一直想說卻說不出口？', is_reversed: false },
  { card_name: '聖杯八', meaning: '你決定暫時離開這個對話，這需要誠實，也需要勇氣。',
    projective_question: '現在，有什麼是你真的不想再想的事？', is_reversed: false },
  // 權杖（能量停頓 / 憤怒凝結）
  { card_name: '權杖九', meaning: '你已經撐了很久了。還沒到終點，但你比自己以為的更有韌性。',
    projective_question: '這份「隨便」或「算了」，是累了，還是有別的話還沒說？', is_reversed: false },
  { card_name: '權杖六', meaning: '你做到了某件事，值得讓自己知道這件事。不是驕傲，是誠實。',
    projective_question: '今天讓你感到最沉的事，是什麼？', is_reversed: false },
  // 錢幣（現實消耗 / 身體疲憊）
  { card_name: '錢幣五', meaning: '你現在覺得匱乏，不管是物質上還是情感上。但你不是一個人在外面的雪地裡。',
    projective_question: '現在最需要的支持，是什麼形式的？', is_reversed: false },
  { card_name: '錢幣十', meaning: '你在建立一些比自己更長久的東西，即使現在感覺不到。',
    projective_question: '有什麼事，是你希望我記得的？', is_reversed: false },
];

// ── STAGNANT 塔羅坑 ─────────────────────────────────────────
function _buildTarotDock() {
  const dock = document.createElement('div');
  dock.id = 'stagnant-tarot-dock';
  dock.style.cssText = 'margin:20px 0 4px';

  // 標題
  const label = document.createElement('p');
  label.style.cssText =
    'font-size:9px;letter-spacing:.14em;color:rgba(245,158,11,.5);' +
    'text-transform:uppercase;margin-bottom:8px;text-align:center';
  label.textContent = '✦ 小阿爾克那 · AI 偵測停滯信號為你投影';
  dock.appendChild(label);

  // 依當前分鐘選牌（每次打開可能不同，增加即時感）
  const idx  = new Date().getMinutes() % _STAGNANT_MINOR_POOL.length;
  const card = _STAGNANT_MINOR_POOL[idx];

  // 動態 import TarotFlip 並掛載
  import('./tarot_flip.js')
    .then(({ renderTarotFlip }) => {
      if (!dock.isConnected) return;
      renderTarotFlip(dock, card);
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
