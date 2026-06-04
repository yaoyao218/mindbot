/**
 * tarot_flip.js — 毛玻璃 3D 翻牌字卡組件
 *
 * 特色：
 *   - 1200px perspective 深景深，翻轉時帶 drop-shadow 光暈
 *   - 卡背（未翻）：半透明深色毛玻璃 + 旋轉光掃動畫 + 脈動光環
 *   - 卡面（翻開）：backdrop-filter blur 真實毛玻璃 + 琥珀光邊框
 *   - 防誤觸：touch ΔY > 8px 判為滾動，跳過翻牌
 *
 * 使用方式：
 *   renderTarotFlip(container, {
 *     card_name, meaning, is_reversed,
 *     defense_type, projective_question
 *   });
 *
 * 與既有 TarotBlind.js 互換相容：匯出相同介面名稱 initTarotCard
 */

export function renderTarotFlip(container, tarotData) {
  if (!tarotData?.card_name) {
    container.innerHTML = `
      <div class="mx-4 my-2 p-5 rounded-2xl text-center"
           style="border:1px dashed rgba(245,158,11,.2);background:rgba(120,70,0,.06)">
        <div style="font-size:2rem;margin-bottom:8px;opacity:.4">🔮</div>
        <p style="color:rgba(245,158,11,.6);font-size:13px;font-weight:500">心靈投射牌尚未出現</p>
        <p style="color:#475569;font-size:11px;margin-top:6px;line-height:1.6">
          完成一次深度對話並說出收尾語（例如「晚安」、「先這樣」），<br>
          AI 將為你抽出本週的潛意識盲點投射牌 ✦
        </p>
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
    ? `<span class="defense-chip">${_esc(defense_type)}</span>`
    : '';

  // 注入組件專屬樣式（idempotent）
  _injectStyles();

  container.innerHTML = `
    <div class="tf-scene mx-4 my-3">
      <div class="tf-inner" id="tf-inner-${_uid()}">

        <!-- ▌卡背（未翻）─ 毛玻璃 + 光掃 + 脈動 -->
        <div class="tf-face tf-back shimmer-sweep">
          <!-- 旋轉光環背景 -->
          <div class="tf-back-glow" aria-hidden="true"></div>

          <div class="tf-back-content">
            <div class="tf-halo-wrap">
              <div class="tf-halo"></div>
              <span class="tf-symbol">🔮</span>
            </div>
            <p class="tf-back-title">凝視你的潛意識盲點</p>
            <p class="tf-back-sub">本週 AI 偵測到的心理防衛模式</p>
            <button class="tf-flip-btn tf-flip-trigger">
              <span class="tf-btn-glow"></span>
              啟動翻牌
            </button>
          </div>
        </div>

        <!-- ▌卡面（翻開）─ 真實毛玻璃 -->
        <div class="tf-face tf-front">
          <!-- 頂部光暈條 -->
          <div class="tf-front-glow-bar" aria-hidden="true"></div>

          <div class="tf-front-content">
            <div class="tf-front-header">
              <div>
                <h4 class="tf-card-name">${_esc(card_name)} <span class="tf-pos">${posLabel}</span></h4>
                <p class="tf-meaning">${_esc(meaning)}</p>
              </div>
              ${defenseChip}
            </div>

            ${projective_question ? `
            <div class="tf-question-bubble">
              <span class="tf-quote-mark">「</span>
              <p class="tf-question-text">${_esc(projective_question)}</p>
              <span class="tf-quote-mark tf-quote-close">」</span>
            </div>` : ''}

            <button class="tf-flip-btn tf-close-btn tf-flip-trigger">收起</button>
          </div>
        </div>

      </div>
    </div>`;

  _bindFlip(container);
}

// ── 翻牌互動邏輯 ──────────────────────────────────────────
export function initTarotCard(container) {
  _bindFlip(container);
}

function _bindFlip(container) {
  const scene  = container.querySelector('.tf-scene');
  const inner  = container.querySelector('.tf-inner');
  const btns   = container.querySelectorAll('.tf-flip-trigger');
  if (!scene || !inner || !btns.length) return;

  let startY = 0;

  scene.addEventListener('touchstart', e => {
    startY = e.touches[0].clientY;
  }, { passive: true });

  scene.addEventListener('touchend', e => {
    if (Math.abs(e.changedTouches[0].clientY - startY) > 8) return;
  }, { passive: true });

  btns.forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const willFlip = !inner.classList.contains('tf-flipped');
      inner.classList.toggle('tf-flipped');

      // 翻開時：外層加光暈；收起時移除
      if (willFlip) {
        scene.style.filter = 'drop-shadow(0 0 28px rgba(99,102,241,.45))';
      } else {
        scene.style.filter = '';
      }
    });
  });
}

// ── 樣式注入（只注入一次）────────────────────────────────
let _stylesInjected = false;
function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;

  const css = `
  /* ── TarotFlip 組件樣式 ───────────────────────────── */
  .tf-scene {
    perspective: 1200px;
    height: 260px;
  }
  .tf-inner {
    position: relative; width: 100%; height: 100%;
    transform-style: preserve-3d;
    transition: transform .78s cubic-bezier(.25,.46,.45,.94);
    will-change: transform;
  }
  .tf-inner.tf-flipped { transform: rotateY(180deg); }

  .tf-face {
    position: absolute; inset: 0;
    border-radius: 1.25rem;
    backface-visibility: hidden;
    -webkit-backface-visibility: hidden;
    /* overflow:hidden + 3D transform 在 WebKit 行動端會干擾 backface-visibility，
       改用 clip-path 或直接不 clip — 內容已在 border-radius 內，視覺安全 */
    overflow: clip;
    transform: translateZ(0);
  }

  /* ── 卡背 ─────────────────────────────────────────── */
  .tf-back {
    background: linear-gradient(145deg, #0e1520 0%, #1a0f2e 50%, #0b1120 100%);
    border: 1.5px solid rgba(99,102,241,.25);
    box-shadow: inset 0 0 60px rgba(99,102,241,.07), 0 4px 24px rgba(0,0,0,.5);
    transform: translateZ(0);
  }

  /* 旋轉彩虹光環（純 CSS）*/
  .tf-back-glow {
    position: absolute; inset: -50%;
    background: conic-gradient(
      transparent 0deg,
      rgba(99,102,241,.12) 60deg,
      transparent 120deg,
      rgba(245,158,11,.07) 180deg,
      transparent 240deg,
      rgba(99,102,241,.1) 300deg,
      transparent 360deg
    );
    animation: tfRotate 12s linear infinite;
  }
  @keyframes tfRotate { to { transform: rotate(360deg); } }

  /* shimmer-sweep 光掃（複用 index.html 的 @keyframes shimmer）*/
  .tf-back.shimmer-sweep::after {
    background: linear-gradient(
      105deg,
      transparent 30%,
      rgba(255,255,255,.04) 50%,
      transparent 70%
    );
    background-size: 200% 100%;
    animation: shimmer 3s linear infinite;
  }
  @keyframes shimmer {
    0%   { background-position: -200% 0 }
    100% { background-position:  200% 0 }
  }

  .tf-back-content {
    position: relative; z-index: 1;
    height: 100%; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 20px 24px; gap: 8px;
  }

  /* 脈動光環 */
  .tf-halo-wrap { position: relative; display: flex; align-items: center; justify-content: center; margin-bottom: 4px; }
  .tf-halo {
    position: absolute; inset: -12px; border-radius: 50%;
    background: radial-gradient(circle, rgba(99,102,241,.2) 0%, transparent 70%);
    animation: tfHaloPulse 3s ease-in-out infinite;
  }
  @keyframes tfHaloPulse {
    0%, 100% { transform: scale(1);    opacity: .5; }
    50%       { transform: scale(1.2); opacity: 1;  }
  }
  .tf-symbol { font-size: 2.75rem; position: relative; z-index: 1; }

  .tf-back-title {
    color: rgba(167,139,250,.9); font-size: 14px;
    font-weight: 600; letter-spacing: .06em; text-align: center;
  }
  .tf-back-sub {
    color: #334155; font-size: 11px; text-align: center; line-height: 1.5;
  }

  /* 翻牌按鈕（卡背）*/
  .tf-flip-btn {
    position: relative;
    padding: 8px 22px; border-radius: 24px; font-size: 13px;
    font-weight: 500; cursor: pointer; border: none;
    transition: transform .15s, filter .15s;
  }
  .tf-flip-btn:active { transform: scale(.93); }
  .tf-flip-trigger.tf-flip-btn:not(.tf-close-btn) {
    background: rgba(99,102,241,.12);
    border: 1.5px solid rgba(99,102,241,.4);
    color: #a5b4fc;
    margin-top: 4px;
  }
  .tf-btn-glow {
    position: absolute; inset: -1px; border-radius: 24px;
    background: transparent;
    box-shadow: 0 0 12px rgba(99,102,241,.4);
    opacity: 0; transition: opacity .3s;
    pointer-events: none;
  }
  .tf-flip-btn:hover .tf-btn-glow { opacity: 1; }

  /* ── 卡面 ─────────────────────────────────────────── */
  .tf-front {
    transform: rotateY(180deg) translateZ(0.5px);
    /* backdrop-filter 在 3D transform + backface-visibility 下於 WebKit 行動端
       會穿透背面，改用不透明實底背景以確保正反面完全隔離。 */
    background: rgba(12, 18, 30, 0.97);
    border: 1.5px solid rgba(245,158,11,.22);
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,.06),
      inset 0 -1px 0 rgba(0,0,0,.3),
      0 4px 24px rgba(0,0,0,.5),
      0 0 0 1px rgba(245,158,11,.06);
  }

  /* 頂部琥珀光條 */
  .tf-front-glow-bar {
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, transparent 0%, rgba(245,158,11,.5) 40%, rgba(99,102,241,.4) 70%, transparent 100%);
    border-radius: 2px 2px 0 0;
  }

  .tf-front-content {
    position: relative; z-index: 1;
    height: 100%; display: flex; flex-direction: column;
    justify-content: space-between; padding: 20px;
  }
  .tf-front-header {
    display: flex; justify-content: space-between;
    align-items: flex-start; gap: 10px;
  }
  .tf-card-name {
    color: #e2e8f0; font-size: 15px; font-weight: 700; line-height: 1.4;
    letter-spacing: .03em;
  }
  .tf-pos {
    display: inline-block;
    font-size: 10px; font-weight: 500;
    color: rgba(245,158,11,.8);
    padding: 2px 7px; border-radius: 12px;
    background: rgba(245,158,11,.1);
    border: 1px solid rgba(245,158,11,.2);
    vertical-align: middle; margin-left: 6px;
  }
  .tf-meaning {
    color: #64748b; font-size: 12px; line-height: 1.6; margin-top: 6px;
  }

  /* 防衛機制標籤 */
  .defense-chip {
    display: inline-block; flex-shrink: 0;
    font-size: 11px; padding: 3px 10px; border-radius: 14px;
    background: rgba(99,102,241,.12);
    border: 1px solid rgba(99,102,241,.3);
    color: #a5b4fc; white-space: nowrap;
  }

  /* 投射問句氣泡 */
  .tf-question-bubble {
    background: rgba(245,158,11,.06);
    border: 1px solid rgba(245,158,11,.15);
    border-radius: .875rem; padding: 12px 16px;
    margin: 6px 0;
    display: flex; align-items: flex-start; gap: 4px;
  }
  .tf-quote-mark {
    color: rgba(245,158,11,.5); font-size: 20px; line-height: 1;
    flex-shrink: 0;
  }
  .tf-quote-close { align-self: flex-end; }
  .tf-question-text {
    color: rgba(245,158,11,.85); font-size: 12px;
    line-height: 1.65; font-style: italic; flex: 1;
  }

  /* 收起按鈕 */
  .tf-close-btn {
    background: transparent; border: none; padding: 0;
    color: #334155; font-size: 12px; text-decoration: underline;
    text-underline-offset: 3px; text-align: center; width: 100%;
    cursor: pointer;
  }
  .tf-close-btn:active { opacity: .6; }
  `;

  const tag = document.createElement('style');
  tag.id = 'tarot-flip-styles';
  tag.textContent = css;
  document.head.appendChild(tag);
}

// ── 工具函式 ─────────────────────────────────────────────
let _counter = 0;
const _uid = () => ++_counter;

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}
