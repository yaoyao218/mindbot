/**
 * psych_bubble.js — 三維度心靈氣泡組件
 *
 * 純原生 Canvas，不依賴任何第三方庫。
 * 莫蘭迪色系（煙燻藍 / 冰川灰 / 琥珀金）呈現情緒・認知・需求三個維度。
 * 每個維度設有一個「引力井」，同類氣泡受引力聚攏；氣泡間有軟排斥。
 *
 * 使用方式：
 *   const bubble = new PsychBubble(canvasElement, apiData);
 *   bubble.updateData(newApiData);   // 刷新資料
 *   bubble.destroy();                // 離頁時呼叫
 *
 * apiData 格式（對應 weekly_scheduler 的 triad 欄位）：
 *   {
 *     emotion:   [{ label: string, value: number }],  // value: 0-100
 *     cognition: [{ label: string, value: number }],
 *     need:      [{ label: string, value: number }]
 *   }
 */

// ── 莫蘭迪色系 ───────────────────────────────────────────
const MORANDI = {
  // 煙燻藍 — emotion
  emotion: [
    { light: '#8FAFC4', mid: '#7C9AB5', dark: '#5A7A96', border: 'rgba(124,154,181,0.55)' },
    { light: '#9DBDD0', mid: '#89AABF', dark: '#648A9E', border: 'rgba(137,170,191,0.5)'  },
    { light: '#7B9BB0', mid: '#6B8AA0', dark: '#4E6E85', border: 'rgba(107,138,160,0.5)'  },
  ],
  // 冰川灰 — cognition
  cognition: [
    { light: '#B0C0C9', mid: '#9BADB8', dark: '#758A96', border: 'rgba(155,173,184,0.55)' },
    { light: '#C0CDD5', mid: '#ABBBC4', dark: '#849AAA', border: 'rgba(171,187,196,0.5)'  },
    { light: '#9CAAB4', mid: '#8A99A5', dark: '#677884', border: 'rgba(138,153,165,0.5)'  },
  ],
  // 琥珀金 — need
  need: [
    { light: '#D4B86A', mid: '#C4A55A', dark: '#9C7E3C', border: 'rgba(196,165,90,0.55)'  },
    { light: '#DFCA85', mid: '#CFBA72', dark: '#A69352', border: 'rgba(207,186,114,0.5)'  },
    { light: '#BFA050', mid: '#AF9040', dark: '#887025', border: 'rgba(175,144,64,0.5)'   },
  ],
};

// ── 三個引力井的角度（等邊三角形佈局）───────────────────
//   emotion   → 頂部  (270°)
//   cognition → 右下  (30°)
//   need      → 左下  (150°)
const WELL_ANGLES = {
  emotion:   (270 * Math.PI) / 180,
  cognition: (30  * Math.PI) / 180,
  need:      (150 * Math.PI) / 180,
};

// ── 物理常數 ─────────────────────────────────────────────
const GRAVITY_K  = 0.009;   // 引力強度
const REPULSE_K  = 0.14;    // 氣泡間排斥強度
const DAMPING    = 0.982;   // 速度阻尼（每幀）
const BOUNCE     = 0.45;    // 牆壁彈性
const NOISE_AMP  = 0.025;   // 隨機擾動幅度（防止靜止平衡）

export class PsychBubble {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} data  - { emotion, cognition, need }
   */
  constructor(canvas, data) {
    this.canvas = canvas;
    this.ctx    = canvas.getContext('2d');
    this.bubbles = [];
    this._raf    = null;
    this._wells  = {};            // 三個引力井座標

    this._resizeHandler = () => this._resize();
    window.addEventListener('resize', this._resizeHandler);

    this._resize();
    this._initBubbles(data || {});
    this._startLoop();
  }

  // ── 畫布尺寸同步 ─────────────────────────────────────
  _resize() {
    const parent = this.canvas.parentElement;
    const W = parent?.offsetWidth  || 360;
    const H = parent?.offsetHeight || 280;
    this.canvas.width  = W;
    this.canvas.height = H;
    this.cx = W / 2;
    this.cy = H / 2;

    // 引力井位置：以中心為圓心，半徑 = min(W,H)*0.28
    const wellR = Math.min(W, H) * 0.28;
    for (const [cat, angle] of Object.entries(WELL_ANGLES)) {
      this._wells[cat] = {
        x: this.cx + Math.cos(angle) * wellR,
        y: this.cy + Math.sin(angle) * wellR,
      };
    }

    // 重繪已有氣泡的引力目標（保持相對位置合理）
    if (this.bubbles.length) this._adjustBubblesOnResize();
  }

  _adjustBubblesOnResize() {
    for (const b of this.bubbles) {
      const w = this._wells[b.category];
      if (!w) continue;
      // 若氣泡超出畫布，推回安全區域
      b.x = Math.max(b.r, Math.min(this.canvas.width  - b.r, b.x));
      b.y = Math.max(b.r, Math.min(this.canvas.height - b.r, b.y));
    }
  }

  // ── 初始化氣泡 ────────────────────────────────────────
  _initBubbles(data) {
    this.bubbles = [];
    const categories = ['emotion', 'cognition', 'need'];

    for (const cat of categories) {
      const items  = (data[cat] || []).filter(item => item?.value > 0);
      const colors = MORANDI[cat];
      const well   = this._wells[cat] || { x: this.cx, y: this.cy };

      items.forEach((item, i) => {
        const r      = _valueToRadius(item.value);
        const spread = 40 + r;
        const angle  = (i / Math.max(items.length, 1)) * Math.PI * 2;

        this.bubbles.push({
          x:        well.x + Math.cos(angle) * spread * (0.5 + Math.random() * 0.5),
          y:        well.y + Math.sin(angle) * spread * (0.5 + Math.random() * 0.5),
          vx:       (Math.random() - 0.5) * 0.5,
          vy:       (Math.random() - 0.5) * 0.5,
          r,
          label:    item.label,
          value:    item.value,
          color:    colors[i % colors.length],
          category: cat,
          alpha:    0,         // 淡入
          alphaTarget: 1,
        });
      });
    }
  }

  // ── rAF 主循環 ────────────────────────────────────────
  _startLoop() {
    this._alive = true;   // destroy() 後 tick 不再重排
    const tick = () => {
      if (!this._alive) return;   // 守衛：destroy 後的最後一幀安全退出
      this._physics();
      this._render();
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  // ── 物理更新 ─────────────────────────────────────────
  _physics() {
    const W = this.canvas.width;
    const H = this.canvas.height;

    // 淡入 + 個體運動
    for (const b of this.bubbles) {
      b.alpha += (b.alphaTarget - b.alpha) * 0.04;

      const well = this._wells[b.category] || { x: this.cx, y: this.cy };

      // 引力：拉向對應引力井
      b.vx += (well.x - b.x) * GRAVITY_K;
      b.vy += (well.y - b.y) * GRAVITY_K;

      // 隨機擾動（防靜止）
      b.vx += (Math.random() - 0.5) * NOISE_AMP;
      b.vy += (Math.random() - 0.5) * NOISE_AMP;

      // 阻尼
      b.vx *= DAMPING;
      b.vy *= DAMPING;

      b.x += b.vx;
      b.y += b.vy;

      // 牆壁彈性碰撞（加邊距防止貼邊）
      const margin = b.r + 2;
      if (b.x < margin)     { b.x = margin;     b.vx = Math.abs(b.vx) * BOUNCE; }
      if (b.x > W - margin) { b.x = W - margin; b.vx = -Math.abs(b.vx) * BOUNCE; }
      if (b.y < margin)     { b.y = margin;     b.vy = Math.abs(b.vy) * BOUNCE; }
      if (b.y > H - margin) { b.y = H - margin; b.vy = -Math.abs(b.vy) * BOUNCE; }
    }

    // 氣泡間軟排斥（O(n²)，氣泡數量有限，可接受）
    const n = this.bubbles.length;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a    = this.bubbles[i];
        const b    = this.bubbles[j];
        const dx   = b.x - a.x;
        const dy   = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
        const min  = a.r + b.r + 6;
        if (dist < min) {
          const force = (min - dist) / min * REPULSE_K;
          const nx    = dx / dist;
          const ny    = dy / dist;
          a.vx -= nx * force;
          a.vy -= ny * force;
          b.vx += nx * force;
          b.vy += ny * force;
        }
      }
    }
  }

  // ── 渲染 ─────────────────────────────────────────────
  _render() {
    const ctx = this.ctx;
    const W   = this.canvas.width;
    const H   = this.canvas.height;

    ctx.clearRect(0, 0, W, H);

    // 背景：三個引力井的淡暈圈
    for (const [cat, well] of Object.entries(this._wells)) {
      const color = _wellHintColor(cat);
      const halo  = ctx.createRadialGradient(well.x, well.y, 0, well.x, well.y, 55);
      halo.addColorStop(0,   color + '18');
      halo.addColorStop(1,   color + '00');
      ctx.beginPath();
      ctx.arc(well.x, well.y, 55, 0, Math.PI * 2);
      ctx.fillStyle = halo;
      ctx.fill();
    }

    // 繪製氣泡（由大至小，大的在下層）
    const sorted = [...this.bubbles].sort((a, b) => b.r - a.r);
    for (const b of sorted) {
      if (b.alpha < 0.01) continue;
      ctx.save();
      ctx.globalAlpha = b.alpha;
      _drawBubble(ctx, b);
      ctx.restore();
    }

    // 引力井分類標籤
    this._renderCategoryLabels(ctx);
  }

  _renderCategoryLabels(ctx) {
    const LABELS = {
      emotion:   { text: '情緒', emoji: '🌊' },
      cognition: { text: '認知', emoji: '🧠' },
      need:      { text: '需求', emoji: '🌱' },
    };
    ctx.save();
    ctx.font         = '10px -apple-system, sans-serif';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';

    for (const [cat, well] of Object.entries(this._wells)) {
      const lbl    = LABELS[cat];
      const color  = _wellHintColor(cat);
      ctx.fillStyle = color + 'aa';
      ctx.fillText(`${lbl.emoji} ${lbl.text}`, well.x, well.y + 62);
    }
    ctx.restore();
  }

  // ── 公開 API ─────────────────────────────────────────

  /** 淡出所有氣泡，用新資料重新生成並淡入 */
  updateData(apiData) {
    // 讓現有氣泡淡出
    for (const b of this.bubbles) b.alphaTarget = 0;

    // 200ms 後重建（配合淡出時間）
    setTimeout(() => {
      this._initBubbles(apiData || {});
    }, 220);
  }

  /** 銷毀動畫、事件監聽並觸發 GC */
  destroy() {
    this._alive = false;
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
    window.removeEventListener('resize', this._resizeHandler);
    // canvas.width = 0 解除 GPU 紋理佔用，提示瀏覽器 GC
    if (this.canvas) {
      this.canvas.width  = 0;
      this.canvas.height = 0;
    }
    this.bubbles = [];
  }
}

// ── 私有繪製函式 ─────────────────────────────────────────

function _drawBubble(ctx, b) {
  const { x, y, r, label, value, color } = b;

  // 主體漸層（左上高光模擬球面）
  const grad = ctx.createRadialGradient(
    x - r * 0.28, y - r * 0.28, r * 0.05,
    x,            y,            r
  );
  grad.addColorStop(0,    color.light + 'ee');
  grad.addColorStop(0.55, color.mid   + 'bb');
  grad.addColorStop(1,    color.dark  + '77');

  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = grad;
  ctx.fill();

  // 邊框
  ctx.strokeStyle = color.border;
  ctx.lineWidth   = 1;
  ctx.stroke();

  // 頂部高光（小橢圓）
  ctx.save();
  ctx.globalAlpha *= 0.5;
  const hl = ctx.createRadialGradient(
    x - r * 0.22, y - r * 0.32, 0,
    x - r * 0.15, y - r * 0.25, r * 0.45
  );
  hl.addColorStop(0, 'rgba(255,255,255,0.35)');
  hl.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = hl;
  ctx.fill();
  ctx.restore();

  // 文字標籤
  const fontSize = r > 38 ? 12 : r > 28 ? 11 : 10;
  ctx.font         = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`;
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle    = 'rgba(240,240,245,0.92)';
  ctx.fillText(label, x, y + (r > 36 ? 2 : 1));

  // 強度數值（大氣泡右上角）
  if (r > 30) {
    ctx.font      = `9px -apple-system, sans-serif`;
    ctx.fillStyle = color.border;
    ctx.fillText(String(value), x + r * 0.62, y - r * 0.58);
  }
}

// ── 工具函式 ─────────────────────────────────────────────
function _valueToRadius(value) {
  // value 0-100 → radius 18-52
  return 18 + (Math.min(100, Math.max(0, value)) / 100) * 34;
}

function _wellHintColor(cat) {
  return cat === 'emotion'   ? '#7C9AB5'
       : cat === 'cognition' ? '#9BADB8'
       : /* need */            '#C4A55A';
}
