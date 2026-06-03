/**
 * Settings.js — 數據自主管理
 *
 * 規格書對齊：
 * - Modal 函數命名：renderLineAlertModal / renderTextareaFallback
 * - JSON 全大寫（原生全域物件）
 * - 日期字串：.toISOString().slice(0, 10)
 * - LINE UA 偵測 → 剪貼簿 → Textarea fallback
 */

import { db, getSetting } from '../db.js';
import { toggleLocalBackup } from './Timeline.js';

/**
 * @param {HTMLElement} container
 * @param {Object}      opts  { userName, lastSync, onExport, onLogout, onBackup }
 */
export async function renderSettings(container, opts = {}) {
  const { userName = '用戶', lastSync = '未知', onExport, onLogout, onBackup } = opts;
  const backupEnabled = await getSetting('keep_local_history', false);

  container.innerHTML = `
    <div class="animate-fade-in px-4 py-5 space-y-4">

      <!-- 帳號 -->
      <div class="bg-glow-card rounded-2xl p-4 border border-white/5 space-y-3">
        <p class="text-xs text-slate-500 uppercase tracking-widest">帳號</p>
        <div class="flex justify-between items-center">
          <span class="text-sm text-slate-300">${_esc(userName)}</span>
          <span class="text-xs text-emerald-400/70 border border-emerald-500/20
                       rounded-full px-2 py-0.5">已連結 LINE</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-xs text-slate-500">最後同步</span>
          <span class="text-xs text-slate-400">${_esc(lastSync)}</span>
        </div>
      </div>

      <!-- 隱私與留存 -->
      <div class="bg-glow-card rounded-2xl p-4 border border-white/5 space-y-3">
        <p class="text-xs text-slate-500 uppercase tracking-widest">隱私與留存</p>

        <div class="flex items-start justify-between gap-3">
          <div class="flex-1">
            <p class="text-sm text-slate-200 font-medium">本地日記備份</p>
            <p class="text-xs text-slate-500 mt-0.5 leading-relaxed">
              雲端無痕・本地留痕：對話保存在此裝置
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer flex-shrink-0 mt-0.5">
            <input type="checkbox" id="toggle-local-backup" class="sr-only peer"
                   ${backupEnabled ? 'checked' : ''}>
            <div class="w-11 h-6 bg-slate-700 rounded-full peer
                        peer-checked:after:translate-x-full peer-checked:after:border-white
                        after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                        after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all
                        peer-checked:bg-glow-primary"></div>
          </label>
        </div>

        <!-- 隱私防護說明 -->
        <div class="rounded-xl bg-slate-800/50 border border-slate-700/40 p-3.5">
          <p class="text-xs text-slate-400 leading-relaxed">
            🔒 <strong class="text-slate-300">隱私防護說明</strong><br>
            MindBot 每週一凌晨完全銷毀伺服器原始對話。開啟後，對話儲存在
            <strong class="text-glow-text">此裝置（IndexedDB）</strong>。
            關閉時，本機對話將<strong class="text-red-400">立即物理銷毀</strong>，
            無法從伺服器恢復。
          </p>
        </div>

        <div class="flex justify-between items-center text-xs text-slate-500">
          <span>雲端資料保留期</span><span>7 天</span>
        </div>
      </div>

      <!-- 資料 -->
      <div class="bg-glow-card rounded-2xl p-4 border border-white/5 space-y-3">
        <p class="text-xs text-slate-500 uppercase tracking-widest">資料</p>
        <div class="flex justify-between items-center">
          <div>
            <p class="text-sm text-slate-200">匯出所有資料</p>
            <p class="text-xs text-slate-500 mt-0.5">週報 + 本地對話打包為 JSON</p>
          </div>
          <button id="export-btn"
                  class="px-4 py-1.5 rounded-xl bg-indigo-950/60 border border-indigo-500/20
                         text-indigo-300 text-xs font-medium active:scale-95 transition">
            📤 匯出
          </button>
        </div>
      </div>

      <!-- 危險區 -->
      <div class="bg-red-950/20 rounded-2xl p-4 border border-red-500/15 space-y-3">
        <p class="text-xs text-red-400/70 uppercase tracking-widest">危險操作</p>
        <div class="flex justify-between items-center">
          <div>
            <p class="text-sm text-slate-200">刪除所有資料</p>
            <p class="text-xs text-slate-500 mt-0.5">本機與雲端同步清除，無法復原</p>
          </div>
          <button id="delete-all-btn"
                  class="px-4 py-1.5 rounded-xl bg-red-950/60 border border-red-500/20
                         text-red-400 text-xs font-medium active:scale-95 transition">
            刪除
          </button>
        </div>
      </div>

      <button id="logout-btn"
              class="w-full py-3 rounded-2xl bg-glow-card border border-white/5
                     text-slate-400 text-sm active:scale-98 transition">
        登出
      </button>
    </div>`;

  // Toggle 備份
  const tog = container.querySelector('#toggle-local-backup');
  tog?.addEventListener('change', async () => {
    const result = await toggleLocalBackup(tog.checked);
    if (onBackup) onBackup(tog.checked);
  });

  // 匯出
  container.querySelector('#export-btn')?.addEventListener('click', () => {
    if (onExport) onExport();
    else exportUserData(container);
  });

  // 刪除全部
  container.querySelector('#delete-all-btn')?.addEventListener('click', () => {
    _confirmDeleteAll(container);
  });

  // 登出
  container.querySelector('#logout-btn')?.addEventListener('click', () => {
    if (onLogout) onLogout();
  });
}

/* ── 資料匯出 ─────────────────────────────────────────── */
export async function exportUserData(uiContainer) {
  const exportPayload = {
    export_at: new Date().toISOString(),
    data: {
      weekly_reports:      await db.archives.toArray(),
      local_conversations: await db.conversations.toArray(),
    },
  };

  const jsonString  = JSON.stringify(exportPayload, null, 2);   // JSON 全大寫（正確）
  const dateFilename = new Date().toISOString().slice(0, 10);   // 規格書：.slice(0, 10)
  const isLineBrowser = /Line/i.test(navigator.userAgent);

  if (isLineBrowser) {
    try {
      await navigator.clipboard.writeText(jsonString);
      // 規格書命名：renderLineAlertModal
      renderLineAlertModal(
        uiContainer,
        '已複製數據！\n\n因 LINE 限制無法直接下載，\n請點選右上角「···」以系統瀏覽器開啟後下載，\n或將剪貼簿文字貼至備忘錄。'
      );
    } catch {
      // 規格書命名：renderTextareaFallback
      renderTextareaFallback(uiContainer, jsonString);
    }
    return;
  }

  // 標準瀏覽器：Blob 下載
  const blob = new Blob([jsonString], { type: 'application/json;charset=utf-8' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `mindbot_backup_${dateFilename}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  _toast('資料已匯出 ✓');
}

/* ── 規格書命名：renderLineAlertModal ─────────────────── */
export function renderLineAlertModal(container, message) {
  const div = document.createElement('div');
  div.className = 'modal-overlay';
  div.innerHTML = `
    <div class="modal-sheet max-w-sm">
      <p class="text-amber-200 text-sm leading-relaxed mb-5 whitespace-pre-line">
        ${_esc(message)}
      </p>
      <button class="w-full py-2.5 rounded-xl bg-amber-500/20 text-amber-300 text-xs
                     font-semibold border border-amber-500/30 active:scale-98 transition">
        確認
      </button>
    </div>`;
  div.querySelector('button').onclick = () => div.remove();
  document.body.appendChild(div);
}

/* ── 規格書命名：renderTextareaFallback ───────────────── */
export function renderTextareaFallback(container, rawText) {
  const div = document.createElement('div');
  div.className = 'modal-overlay';
  div.style.background = 'rgba(0,0,0,.93)';
  div.innerHTML = `
    <div class="w-full px-4 pb-8" style="max-height:90vh">
      <p class="text-slate-300 text-xs mb-2">請長按全選下方文字進行複製備份：</p>
      <textarea class="w-full h-56 bg-slate-950 text-emerald-400 p-3 text-xs rounded-xl
                       border border-slate-800 font-mono" readonly>${_esc(rawText)}</textarea>
      <button class="mt-3 w-full py-2.5 rounded-xl bg-slate-800 text-slate-300 text-xs
                     active:scale-98 transition">關閉</button>
    </div>`;
  div.querySelector('button').onclick = () => div.remove();
  document.body.appendChild(div);
}

/* ── 私有工具 ─────────────────────────────────────────── */
function _confirmDeleteAll(container) {
  const div = document.createElement('div');
  div.className = 'modal-overlay';
  div.innerHTML = `
    <div class="modal-sheet max-w-sm">
      <h3 class="text-red-400 font-bold mb-2">確認刪除所有資料？</h3>
      <p class="text-slate-400 text-sm leading-relaxed mb-5">
        此操作清除本裝置所有週報與對話，<strong class="text-red-400">無法復原</strong>。
      </p>
      <div class="flex gap-3">
        <button id="cancel-del" class="flex-1 py-2.5 rounded-xl bg-slate-800 text-slate-300
                                       text-sm active:scale-98 transition">取消</button>
        <button id="confirm-del" class="flex-1 py-2.5 rounded-xl bg-red-900/60 text-red-300
                                        border border-red-500/20 text-sm active:scale-98 transition">
          確認刪除
        </button>
      </div>
    </div>`;
  div.querySelector('#cancel-del').onclick = () => div.remove();
  div.querySelector('#confirm-del').onclick = async () => {
    await Promise.all([db.archives.clear(), db.conversations.clear()]);
    div.remove();
    _toast('所有本機資料已清除');
  };
  document.body.appendChild(div);
}

function _toast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2800);
}

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
