/**
 * WelcomeModal.js — 首次登入三步驟引導彈窗
 *
 * 觸發條件：Dexie user_settings.has_boarded 不存在或 false
 * 完成條件：第三步點擊「開啟今日沉澱」→ 寫入 has_boarded:true → 自動關閉
 */

import { setSetting } from '../db.js';

const LIFF_URL = 'https://liff.line.me/2010279401-zI4pqH8D';

const STEPS = [
  {
    emoji: '🌿',
    title: '歡迎來到你的深夜避風港',
    body:
      '這裡是一個沒有評判、完全屬於你內心的安全容器。' +
      '你在此處留下的每一句碎碎念、每一次委屈，都將轉化為陪伴你成長的養分。',
    btn: '這裡安全嗎？',
  },
  {
    emoji: '🔒',
    title: '你的心事，鎖在你的手機裡',
    body:
      '我們嚴格遵循「雲端無痕，本地留痕」原則。每週一凌晨雲端將徹底抹除你的原始對話。' +
      '如果你開啟了「本地備份」，心事字泡將會加密物理鎖定在你這台手機的資料庫中，連我們也無法偷看。',
    btn: '認識陪伴機制',
  },
  {
    emoji: '🔮',
    title: '捕捉潛意識的火花',
    body:
      '當你在 LINE 與我對話時，我不僅會傾聽，還會在你收尾或陷入僵局時，' +
      '為你抽出一張「心靈投射卡片」（塔羅隱喻）。這些發現會點亮你情緒月曆上的金色 ✦ 星號。',
    btn: '開啟今日沉澱 ✦',
    isLast: true,
  },
];

/**
 * @param {HTMLElement} container  掛載目標（通常是 document.body 或 #app-screen）
 * @param {Function}    onDone     完成後的回呼（關閉 Modal 後呼叫）
 */
export function renderWelcomeModal(container, onDone) {
  let step = 0;

  const overlay = document.createElement('div');
  overlay.id = 'welcome-overlay';
  overlay.style.cssText = `
    position:fixed;inset:0;z-index:300;
    background:rgba(7,9,18,0.92);
    display:flex;align-items:flex-end;justify-content:center;
    animation:fadeIn .4s ease both;
  `;

  overlay.innerHTML = `
    <div id="welcome-card" style="
      width:100%;max-width:480px;
      background:linear-gradient(to bottom,#0f172a,#1e1b4b);
      border-radius:24px 24px 0 0;
      border:1px solid rgba(99,102,241,0.2);
      border-bottom:none;
      box-shadow:0 0 40px rgba(99,102,241,0.15),0 -4px 60px rgba(99,102,241,0.08);
      padding:32px 24px 40px;
      padding-bottom:max(40px,calc(40px + env(safe-area-inset-bottom)));
    ">
      <!-- 進度點 -->
      <div id="wm-dots" style="display:flex;justify-content:center;gap:6px;margin-bottom:28px"></div>

      <!-- 內容區 -->
      <div id="wm-emoji"  style="font-size:3rem;text-align:center;margin-bottom:16px"></div>
      <h2  id="wm-title"  style="font-size:1.1rem;font-weight:700;color:#e2e8f0;
                                  text-align:center;margin-bottom:12px;line-height:1.4"></h2>
      <p   id="wm-body"   style="font-size:0.85rem;color:#94a3b8;line-height:1.75;
                                  text-align:center;margin-bottom:28px;min-height:80px"></p>

      <!-- 主按鈕 -->
      <button id="wm-btn" style="
        width:100%;padding:14px;border-radius:14px;
        background:linear-gradient(135deg,rgba(99,102,241,0.25),rgba(139,92,246,0.2));
        border:1px solid rgba(99,102,241,0.4);
        color:#c7d2fe;font-size:0.9rem;font-weight:600;
        cursor:pointer;letter-spacing:.04em;
        transition:opacity .2s,transform .1s;
      "></button>

      <!-- 跳過 -->
      <button id="wm-skip" style="
        width:100%;margin-top:12px;padding:8px;
        background:none;border:none;
        color:#475569;font-size:0.75rem;cursor:pointer;
      ">稍後再說</button>
    </div>`;

  container.appendChild(overlay);

  const dotsEl = overlay.querySelector('#wm-dots');
  const emojiEl = overlay.querySelector('#wm-emoji');
  const titleEl = overlay.querySelector('#wm-title');
  const bodyEl  = overlay.querySelector('#wm-body');
  const btnEl   = overlay.querySelector('#wm-btn');
  const skipEl  = overlay.querySelector('#wm-skip');

  function renderStep(i) {
    const s = STEPS[i];

    // 更新進度點
    dotsEl.innerHTML = STEPS.map((_, idx) => `
      <span style="
        width:${idx === i ? 20 : 6}px;height:6px;border-radius:3px;
        background:${idx === i ? '#6366f1' : 'rgba(99,102,241,0.25)'};
        transition:all .3s;display:inline-block;
      "></span>`).join('');

    // 淡入動畫
    [emojiEl, titleEl, bodyEl].forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(8px)';
    });
    emojiEl.textContent = s.emoji;
    titleEl.textContent = s.title;
    bodyEl.textContent  = s.body;
    btnEl.textContent   = s.btn;

    requestAnimationFrame(() => {
      [emojiEl, titleEl, bodyEl].forEach((el, idx) => {
        setTimeout(() => {
          el.style.transition = 'opacity .35s ease, transform .35s ease';
          el.style.opacity  = '1';
          el.style.transform = 'translateY(0)';
        }, idx * 60);
      });
    });

    // 最後一步才顯示「稍後再說」
    skipEl.style.display = s.isLast ? 'block' : 'none';
  }

  async function complete() {
    await setSetting('has_boarded', true);
    overlay.style.opacity = '0';
    overlay.style.transition = 'opacity .3s ease';
    setTimeout(() => {
      overlay.remove();
      onDone?.();
    }, 300);
  }

  btnEl.addEventListener('click', async () => {
    if (STEPS[step].isLast) {
      await complete();
    } else {
      step++;
      renderStep(step);
    }
  });

  skipEl.addEventListener('click', () => complete());

  // 按鈕 hover 效果
  btnEl.addEventListener('mouseenter', () => { btnEl.style.opacity = '0.85'; });
  btnEl.addEventListener('mouseleave', () => { btnEl.style.opacity = '1'; });
  btnEl.addEventListener('mousedown',  () => { btnEl.style.transform = 'scale(0.98)'; });
  btnEl.addEventListener('mouseup',    () => { btnEl.style.transform = 'scale(1)'; });

  renderStep(0);
}
