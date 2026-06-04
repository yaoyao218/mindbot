/**
 * app.js — AppController
 * 規格書：class AppController，掛載至 window.MindBotApp，DOMContentLoaded 啟動
 */

import { db, getSetting, setSetting }          from './db.js';
import { renderDashboard }                     from './components/Dashboard.js';
import { renderTarotFlip as renderTarotBlind, initTarotCard } from './components/tarot_flip.js';
import { renderCalendar }                      from './components/CalendarView.js';
import { renderTimeline, toggleLocalBackup }   from './components/Timeline.js';
import { renderSettings, exportUserData }      from './components/Settings.js';
import { renderWelcomeModal }                  from './components/WelcomeModal.js';

class AppController {
  constructor() {
    this.currentRoute   = 'dashboard';
    this._token         = null;
    this._userId        = null;
    this._userName      = null;
    this._calYear       = new Date().getFullYear();
    this._calMonth      = new Date().getMonth() + 1;
    this._lineAccountId = '';   // 從 /api/config 載入，取代硬寫的 @mindbot
  }

  /* ── 啟動入口 ─────────────────────────────────── */
  async init() {
    // ★ 看門狗：無論任何情況，5 秒後強制開門，絕對不讓使用者卡死
    const watchdog = setTimeout(() => {
      console.warn('[App] ★ Watchdog fired: 5s elapsed, forcing UI open');
      this._forceOpen();
    }, 5000);

    try {
      this._token    = localStorage.getItem('mb_token');
      this._userId   = localStorage.getItem('mb_user_id');
      this._userName = localStorage.getItem('mb_name') || '用戶';

      // 載入 LIFF_ID — 使用帶 timeout 的 _api()，避免 Railway 冷啟動卡死
      try {
        const cfg = await this._api('/api/config');   // ← 8s timeout 保護
        if (cfg.line_account_id) this._lineAccountId = cfg.line_account_id;
        if (cfg.liff_id && window.liff) {
          // liff.init() 本身沒有 timeout，用 Promise.race 加上 6s 熔斷
          await Promise.race([
            this._initLiff(cfg.liff_id),
            new Promise((_, rej) =>
              setTimeout(() => rej(new Error('liff.init timeout')), 6000)
            ),
          ]);
        }
      } catch (err) {
        console.warn('[App] config/LIFF failed, using cached token:', err.message);
      }

      if (!this._token) {
        clearTimeout(watchdog);
        document.getElementById('loading-screen').innerHTML =
          '<p class="text-red-400 text-sm px-8 text-center mt-8">請先登入 LINE</p>';
        return;
      }

      clearTimeout(watchdog);
      this._forceOpen();   // 正常流程開門

    } catch (criticalErr) {
      clearTimeout(watchdog);
      console.error('[App] init critical error:', criticalErr);
      this._forceOpen();
    }
  }

  /** 隱藏 loading、顯示 app、綁定導航 — 可安全重複呼叫 */
  _forceOpen() {
    try {
      const ls = document.getElementById('loading-screen');
      const as = document.getElementById('app-screen');
      if (ls) ls.style.display = 'none';
      if (as) as.style.display = 'block';

      // 避免重複綁定
      if (!this._navBound) {
        this._navBound = true;
        this._bindNav();
        this._bindGlobalCalendarDelegate();
        window.addEventListener('hashchange', () => this.navigate(window.location.hash));
      }

      this.navigate(window.location.hash || '#dashboard');
      this.syncBackground().catch(e => console.warn('[Sync]', e));

      // 首次登入引導（非阻塞，不影響 navigate）
      this._checkFirstTimeUser().catch(() => {});
    } catch (_) { /* DOM 也爛了就放棄 */ }
  }

  /** 首次登入：檢查 has_boarded，尚未完成則彈出引導彈窗 */
  async _checkFirstTimeUser() {
    const hasBoarded = await getSetting('has_boarded', false);
    if (!hasBoarded) {
      renderWelcomeModal(document.body, () => {
        // 關閉後重新渲染當前頁（讓 Dashboard 刷新 CTA 狀態）
        this.navigate(window.location.hash || '#dashboard');
      });
    }
  }

  /* ── LIFF 初始化 ─────────────────────────────── */
  async _initLiff(liffId) {
    await liff.init({ liffId });
    if (!liff.isLoggedIn()) {
      liff.login({ redirectUri: location.href });
      return;
    }
    const lineToken = liff.getAccessToken();
    const profile   = await liff.getProfile();
    const resp = await fetch('/api/auth/line_callback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ liff_token: lineToken }),
    });
    if (!resp.ok) throw new Error('Backend auth failed');
    const { token, user_id, name } = await resp.json();
    this._token    = token;
    this._userId   = user_id;
    this._userName = name || profile.displayName || '用戶';
    localStorage.setItem('mb_token',   this._token);
    localStorage.setItem('mb_user_id', this._userId);
    localStorage.setItem('mb_name',    this._userName);
  }

  /* ── 路由 ────────────────────────────────────── */
  navigate(hash) {
    this.currentRoute = (hash || '#dashboard').replace('#', '') || 'dashboard';
    const container   = document.getElementById('app-runtime');
    if (!container) return;

    // 底部 Nav 高亮
    document.querySelectorAll('[data-nav]').forEach(el => {
      const active = el.dataset.nav === this.currentRoute;
      el.classList.toggle('text-glow-primary', active);
      el.classList.toggle('text-slate-500',    !active);
    });

    history.replaceState({}, '', `#${this.currentRoute}`);
    this._renderRoute(container, this.currentRoute);
  }

  async _renderRoute(container, route) {
    // 離開前清除 Canvas rAF，防止記憶體洩漏
    window._mbPsychBubble?.destroy(); window._mbPsychBubble = null;
    window._mbWaveChart?.destroy();   window._mbWaveChart   = null;

    // 骨架屏
    container.innerHTML = `
      <div class="px-4 py-6 space-y-3">
        <div class="skeleton h-36 rounded-2xl"></div>
        <div class="skeleton h-20 rounded-2xl"></div>
        <div class="skeleton h-48 rounded-2xl"></div>
      </div>`;

    try {
      switch (route) {
        case 'dashboard': await this._loadDashboard(container); break;
        case 'calendar':  await this._loadCalendar(container);  break;
        case 'timeline':  await this._loadTimeline(container);  break;
        case 'settings':  await this._loadSettings(container);  break;
        default:          await this._loadDashboard(container);
      }
    } catch (e) {
      console.error(`[App] _renderRoute(${route}) failed:`, e);
      container.innerHTML =
        '<div class="text-center py-16 text-slate-500 text-sm">載入失敗，請重新整理</div>';
    }
  }

  /* ── Dashboard ───────────────────────────────── */
  async _loadDashboard(container) {
    let snapData = null;
    try {
      snapData = await this._api('/api/snapshot');
    } catch {
      const local = await db.archives.orderBy('id').last();
      if (local) snapData = local;
    }
    renderDashboard(container, snapData);

    // 塔羅盲點翻牌元件：有資料顯示牌面，無資料顯示「尚未偵測」引導提示
    // 無論有無資料都渲染，確保功能可被發現
    const pc = snapData?.psych_context || {};
    const tarotWrap = document.createElement('div');
    container.appendChild(tarotWrap);
    renderTarotBlind(tarotWrap, pc.tarot_card ? {
      card_name:           pc.tarot_name_zh || pc.tarot_card,
      meaning:             pc.tarot_meaning || '',
      projective_question: pc.dialogue_insight || '',
    } : null);   // null → tarot_flip.js 顯示「尚未偵測到潛意識盲點」空態
  }

  /* ── Calendar ────────────────────────────────── */
  async _loadCalendar(container) {
    let records = [];
    try {
      const data = await this._api(
        `/api/emotion-calendar?year=${this._calYear}&month=${this._calMonth}`
      );
      records = data.records || [];
    } catch (e) {
      console.warn('[App] emotion-calendar fetch failed:', e);
    }
    renderCalendar(container, this._calYear, this._calMonth, records);

    // 月份切換事件
    container.addEventListener('month-change', async e => {
      this._calYear  = e.detail.year;
      this._calMonth = e.detail.month;
      await this._loadCalendar(container);
    }, { once: true });
  }

  /* ── Timeline ────────────────────────────────── */
  async _loadTimeline(container) {
    const keepLocal = await getSetting('keep_local_history', false);
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
    const messages = await db.conversations.orderBy('timestamp').toArray();
    renderTimeline(container, messages);
  }

  /* ── Settings ────────────────────────────────── */
  async _loadSettings(container) {
    const lastSync = localStorage.getItem('mb_lastsync') || '未知';
    await renderSettings(container, {
      userName: this._userName,
      lastSync,
      onExport:  () => exportUserData(container),
      onLogout:  () => this._logout(),
      onBackup:  async (checked) => {
        const result = await toggleLocalBackup(checked);
        this.showToast(result ? '💾 本地備份已開啟' : '🔒 本地對話已物理銷毀');
        if (this.currentRoute === 'timeline') {
          await this._loadTimeline(document.getElementById('app-runtime'));
        }
      },
    });
  }

  /* ── 全域 CalendarView 事件委派（規格書要求）─── */
  _bindGlobalCalendarDelegate() {
    const runtime = document.getElementById('app-runtime');
    if (!runtime) return;
    runtime.addEventListener('click', e => {
      const cell = e.target.closest('[data-date]');
      if (!cell) return;
      const dateStr = cell.getAttribute('data-date');
      const isEmpty = cell.getAttribute('data-empty') === 'true';
      if (isEmpty) {
        this._openCreateModal(dateStr);
      } else {
        this._openDetailModal(dateStr);
      }
    });
  }

  _openDetailModal(dateStr) {
    if (!dateStr) return;
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-sheet">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-glow-text font-semibold">${dateStr}</h3>
          <button class="close-modal text-slate-500 text-xl">×</button>
        </div>
        <div class="modal-body">
          <div class="skeleton h-20 rounded-xl mb-3"></div>
        </div>
      </div>`;
    overlay.querySelector('.close-modal').onclick = () => overlay.remove();
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);

    this._api(`/api/daily-record?date=${dateStr}`).then(data => {
      const mc = overlay.querySelector('.modal-body');
      if (!data || data.error) {
        mc.innerHTML = '<p class="text-slate-500 text-sm text-center py-4">這天還沒有紀錄</p>';
        return;
      }
      mc.innerHTML = `
        ${data.emotion_emoji ? `<div class="text-4xl text-center mb-3">${data.emotion_emoji}</div>` : ''}
        ${data.emotion_label ? `<p class="text-xs text-slate-500 text-center mb-3">${data.emotion_label}</p>` : ''}
        ${data.tarot_card    ? `<div class="text-xs text-amber-400 border border-amber-500/20 rounded-full px-3 py-1 inline-flex mb-3">🔮 ${data.tarot_card}</div>` : ''}
        ${data.daily_narrative ? `<p class="text-slate-300 text-sm leading-relaxed">${data.daily_narrative}</p>` : ''}`;
    }).catch(() => {
      overlay.querySelector('.modal-body').innerHTML =
        '<p class="text-slate-500 text-sm text-center py-4">載入失敗</p>';
    });
  }

  _openCreateModal(dateStr) {
    const isToday = dateStr === new Date().toISOString().slice(0, 10);
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-sheet">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-glow-text font-semibold">${dateStr}</h3>
          <button class="close-modal text-slate-500 text-xl leading-none">×</button>
        </div>
        <p class="text-slate-300 text-sm leading-relaxed mb-2">
          今天還沒有留下心事蹤跡。
        </p>
        <p class="text-slate-400 text-sm leading-relaxed mb-5">
          ${isToday
            ? '今晚睡前，試著到聊天室對我說：<br><span class="text-amber-300 font-medium">「🛌 睡前安靜聊聊」</span><br>來點亮今天的金色 ✦ 星號吧！'
            : '回到 LINE 聊天室，跟心事日記說說最近的心情，這裡就會出現你的情緒足跡 🌿'}
        </p>
        <button id="cta-go-line"
                class="w-full py-3 rounded-xl text-sm font-medium
                       bg-indigo-950/60 border border-indigo-500/30
                       text-indigo-300 active:scale-95 transition mb-3">
          🪐 前往 LINE 開啟對話
        </button>
        <button class="close-modal w-full py-2 rounded-xl bg-glow-card border border-white/8
                       text-slate-500 text-sm active:scale-98 transition">
          稍後再說
        </button>
      </div>`;

    const goLine = overlay.querySelector('#cta-go-line');
    goLine?.addEventListener('click', () => {
      overlay.remove();
      if (window.liff?.isInClient()) {
        window.liff.closeWindow();
      } else {
        const id = window.MindBotApp?._lineAccountId;
        window.open(id ? `https://line.me/R/ti/p/${id}` : 'https://line.me/', '_blank');
      }
    });

    overlay.querySelectorAll('.close-modal').forEach(b => b.onclick = () => overlay.remove());
    document.body.appendChild(overlay);
  }

  /* ── 同步（指數退避 Retry + 對話緩衝同步）────── */

  /**
   * @param {number} retryCount  目前重試次數（0 = 首次）
   * 最多重試 3 次，退避間隔：1s → 2s → 4s
   */
  async syncBackground(retryCount = 0) {
    const syncLabel = document.getElementById('sync-label');

    if (syncLabel) {
      syncLabel.textContent = '同步中...';
      syncLabel.className   = 'text-xs text-amber-400 font-medium animate-pulse';
    }

    try {
      // 軌道 1：週報增量同步（PostgreSQL SSOT）
      const { reports = [] } = await this._api('/api/sync/weekly');
      for (const r of reports) {
        await db.archives.put({ ...r, id: r.week_id });
      }
      if (reports.length) this.showToast(`已同步 ${reports.length} 份週報`);

      // 軌道 2：隱私安全檢查 → 對話同步
      const keepLocalHistory = await getSetting('keep_local_history', true);
      if (keepLocalHistory && this._userId) {
        await this._syncConversations();
      }

      const now = new Date().toLocaleString('zh-Hant');
      localStorage.setItem('mb_lastsync', now);

      if (syncLabel) {
        syncLabel.textContent = '● 已同步';
        syncLabel.className   = 'text-xs text-emerald-400 font-medium';
      }

    } catch (error) {
      console.error(`[Sync Retry ${retryCount}/3] (Delay: ${Math.pow(2, retryCount - 1)}s)`, error);
      const maxRetries = 3;

      if (retryCount < maxRetries) {
        const delay = Math.pow(2, retryCount) * 1000;   // 1s → 2s → 4s
        if (syncLabel) syncLabel.textContent = `同步失敗，${delay / 1000}s 後重試...`;
        setTimeout(() => this.syncBackground(retryCount + 1), delay);
      } else {
        if (syncLabel) {
          syncLabel.textContent = '● 離線模式';
          syncLabel.className   = 'text-xs text-rose-400 font-medium';
        }
      }
    }
  }

  /** 對話緩衝區增量寫入 IDB（Transaction 原子 + &msg_key 唯一索引去重） */
  async _syncConversations() {
    const response = await fetch(
      `/api/sync/conversations?user_id=${this._userId}`,
      { headers: { Authorization: `Bearer ${this._token}` } }
    );
    if (!response.ok) throw new Error('Sync API failed');

    const remoteMessages = await response.json();
    const msgs = remoteMessages.messages || remoteMessages || [];
    if (!msgs.length) return;

    await db.transaction('rw', db.conversations, async () => {
      for (const msg of msgs) {
        const key = `${msg.timestamp || msg.created_at || ''}_${msg.role || 'user'}`;
        const exists = await db.conversations.where('msg_key').equals(key).first();
        if (!exists) {
          await db.conversations.put({
            msg_key:   key,
            timestamp: msg.timestamp || msg.created_at || new Date().toISOString(),
            role:      msg.role    || 'user',
            content:   msg.content || msg.text || '',
          });
        }
      }
    });
  }

  /* ── 工具 ────────────────────────────────────── */
  showSkeleton() {
    const container = document.getElementById('app-runtime');
    if (!container) return;
    container.innerHTML = `
      <div class="px-4 py-6 space-y-3">
        <div class="skeleton h-36 rounded-2xl"></div>
        <div class="skeleton h-20 rounded-2xl"></div>
        <div class="skeleton h-48 rounded-2xl"></div>
      </div>`;
  }

  showToast(msg) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2800);
  }

  _api(path, opts = {}) {
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), 8000);
    return fetch(path, {
      ...opts,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(this._token ? { Authorization: `Bearer ${this._token}` } : {}),
        ...opts.headers,
      },
    }).then(r => {
      clearTimeout(tid);

      // 401：Token 已過期或無效 → 清除本地憑證並觸發重新登入閉環
      if (r.status === 401) {
        console.warn('[App] 401 received, clearing credentials and re-login');
        ['mb_token', 'mb_user_id', 'mb_name'].forEach(k => localStorage.removeItem(k));
        this._token  = null;
        this._userId = null;
        // LIFF 環境：重導向至 LINE 登入；非 LIFF：重載頁面觸發 init()
        if (window.liff?.isLoggedIn?.()) {
          window.liff.login({ redirectUri: location.href });
        } else {
          location.reload();
        }
        throw new Error('401 Unauthorized – relogin triggered');
      }

      if (!r.ok) throw new Error(`${r.status} ${path}`);
      return r.json();
    }).catch(e => {
      clearTimeout(tid);
      throw e;
    });
  }

  _bindNav() {
    document.querySelectorAll('[data-nav]').forEach(el => {
      el.addEventListener('click', () => this.navigate(`#${el.dataset.nav}`));
    });
  }

  _logout() {
    ['mb_token','mb_user_id','mb_name'].forEach(k => localStorage.removeItem(k));
    if (window.liff?.isLoggedIn()) liff.logout();
    location.reload();
  }
}

// 規格書：掛載至全域，DOMContentLoaded 啟動
window.MindBotApp = new AppController();
document.addEventListener('DOMContentLoaded', () => window.MindBotApp.init());
