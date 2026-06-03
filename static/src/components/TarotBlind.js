/**
 * TarotBlind.js — 潛意識盲點翻牌元件
 *
 * 規格書防誤觸邏輯：
 * - touchstart / touchend 綁在 card（.tarot-card-container）上，passive: true
 * - ΔY > 8px → 判定為頁面滾動，跳過翻牌
 * - 翻牌僅由 .tarot-flip-btn 的 click 事件觸發
 */

export function renderTarotBlind(container, tarotData) {
  if (!tarotData?.card_name) {
    container.innerHTML = `
      <div class="mx-4 my-2 p-5 rounded-2xl border border-dashed border-amber-500/20
                  bg-amber-950/10 text-center">
        <p class="text-amber-400/60 text-sm">本週尚未偵測到潛意識盲點</p>
        <p class="text-slate-600 text-xs mt-1">繼續在 LINE 傾訴，AI 將持續觀察心理模式</p>
      </div>`;
    return;
  }

  const {
    card_name           = '未知牌',
    meaning             = '',
    is_reversed         = false,
    defense_type        = '',
    projective_question = '',
  } = tarotData;

  const posLabel    = is_reversed ? '逆位' : '正位';
  const defenseChip = defense_type
    ? `<span class="text-xs px-2 py-0.5 rounded bg-indigo-950 border border-indigo-500/30
                   text-indigo-300">${_esc(defense_type)}</span>`
    : '';

  container.innerHTML = `
    <div class="tarot-card-container w-full mx-4" style="height:260px;max-width:calc(100% - 2rem)">
      <div class="tarot-card-inner relative w-full h-full">

        <!-- 正面 -->
        <div class="backface-hidden absolute inset-0 rounded-2xl
                    bg-gradient-to-b from-amber-950 to-slate-900
                    border-2 border-amber-500/30 shadow-lg
                    flex flex-col justify-center items-center p-5">
          <div class="relative mb-3">
            <span class="absolute -inset-4 animate-pulse-slow rounded-full bg-amber-400/10 block"></span>
            <span class="text-5xl relative">🔮</span>
          </div>
          <p class="text-amber-400 text-sm font-semibold tracking-wider mb-1 text-center">
            凝視你的潛意識盲點
          </p>
          <p class="text-slate-500 text-xs mb-5 text-center">本週 AI 偵測到的心理防衛模式</p>
          <button class="tarot-flip-btn px-5 py-2 rounded-full
                         bg-amber-500/10 border border-amber-500/40
                         text-amber-300 text-sm font-medium
                         hover:bg-amber-500/20 active:scale-95 transition">
            啟動翻牌
          </button>
        </div>

        <!-- 背面 -->
        <div class="backface-hidden rotate-Y-180 absolute inset-0 rounded-2xl
                    bg-glow-card border-2 border-indigo-500/30 p-5
                    flex flex-col justify-between">
          <div>
            <div class="flex justify-between items-start mb-2">
              <h4 class="text-indigo-200 font-bold">${_esc(card_name)} ・ ${posLabel}</h4>
              ${defenseChip}
            </div>
            <p class="text-slate-500 text-xs leading-snug">${_esc(meaning)}</p>
          </div>
          ${projective_question ? `
          <div class="bg-indigo-950/40 border border-indigo-500/10 rounded-xl p-3 mt-2">
            <p class="text-amber-300/90 text-xs leading-relaxed italic">
              「${_esc(projective_question)}」
            </p>
          </div>` : ''}
          <button class="tarot-flip-btn mt-3 text-xs text-slate-600 underline
                         underline-offset-2 text-center w-full active:opacity-60 transition">
            收起
          </button>
        </div>
      </div>
    </div>`;

  initTarotCard(container);
}

/**
 * 規格書實作：
 * touchstart / touchend 綁在 card（.tarot-card-container），passive: true
 * ΔY > 8px → 不觸發翻牌
 */
export function initTarotCard(container) {
  const card    = container.querySelector('.tarot-card-container');
  const flipBtn = container.querySelector('.tarot-flip-btn');
  if (!card || !flipBtn) return;

  let startY = 0;

  // 綁在 card 上，passive: true（不阻止瀏覽器預設滾動）
  card.addEventListener('touchstart', (e) => {
    startY = e.touches[0].clientY;
  }, { passive: true });

  card.addEventListener('touchend', (e) => {
    const endY  = e.changedTouches[0].clientY;
    const diffY = Math.abs(endY - startY);
    // 超過 8px → 判定為滾動，跳過（不翻牌）
    if (diffY > 8) return;
  }, { passive: true });

  // 翻牌只由 click 觸發
  container.querySelectorAll('.tarot-flip-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      card.classList.toggle('flipped');
    });
  });
}

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
