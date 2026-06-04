/**
 * wave_chart.js — SVG 情緒潮汐圖
 *
 * 使用原生 SVG 貝茲曲線繪製雙層海浪，以 requestAnimationFrame 驅動緩慢起伏。
 * 情緒強度（1–5）映射為波峰偏移高度，資料點以 emoji + 光暈標記。
 *
 * 使用方式：
 *   const chart = new WaveChart(container, { records });
 *   chart.update(newRecords);          // 即時更新資料點
 *   chart.destroy();                   // 離開頁面時呼叫
 *
 *   // 直接從 API 建立：
 *   const chart = await WaveChart.fromAPI(container, { year, month, token });
 */

// 情緒 emoji → 強度（1–5）的預設映射
const EMOJI_INTENSITY = {
  '😊': 4, '😄': 5, '🥳': 5, '😃': 4,
  '😢': 2, '😭': 1, '😔': 2, '😞': 2,
  '😤': 4, '😡': 5, '😰': 3, '😨': 2,
  '😴': 1, '😶': 2, '😌': 3, '🥺': 2,
  '😮': 4, '🤔': 3, '😑': 2, '🙂': 3,
};

// 強度 → 波形顏色
function intensityColor(avg) {
  if (avg >= 4) return { fill: 'rgba(99,102,241,0.35)',  stroke: '#6366f1' };
  if (avg >= 2.5) return { fill: 'rgba(16,185,129,0.28)', stroke: '#10b981' };
  return             { fill: 'rgba(71, 85,105,0.22)',  stroke: '#475569' };
}

export class WaveChart {
  /**
   * @param {HTMLElement} container
   * @param {{ records?: Array<{date:string, emotion_emoji?:string, arousal_level?:number}> }} data
   */
  constructor(container, data = {}) {
    this.container = container;
    this.records   = data.records || [];
    this._phase    = 0;
    this._raf      = null;
    this._mounted  = false;
    this._mount();
  }

  // ── 掛載 DOM ──────────────────────────────────────────
  _mount() {
    this.container.innerHTML = '';

    // 外層 wrapper
    const wrap = document.createElement('div');
    wrap.style.cssText = [
      'position:relative', 'width:100%', 'height:160px',
      'overflow:hidden',   'border-radius:1rem',
      'background:rgba(7,11,20,0.6)',
      'border:1px solid rgba(99,102,241,0.1)',
    ].join(';');

    // SVG 畫布
    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('width',  '100%');
    this.svg.setAttribute('height', '100%');
    this.svg.setAttribute('preserveAspectRatio', 'none');
    this.svg.style.cssText = 'display:block;position:absolute;inset:0';

    this._buildDefs();

    // 背景波（慢、大振幅、低透明度）
    this._bgPath = this._makePath('url(#wcGradBg)', '#1e293b', 0.5);
    // 主波（含情緒資料偏移）
    this._fgPath = this._makePath('url(#wcGradFg)', '#6366f1', 1);
    // 資料點群組（在波形之上）
    this._dots = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    this.svg.appendChild(this._dots);

    wrap.appendChild(this.svg);

    // 空狀態文字
    this._emptyEl = document.createElement('div');
    this._emptyEl.style.cssText = [
      'position:absolute', 'inset:0', 'display:flex',
      'align-items:center', 'justify-content:center', 'pointer-events:none',
    ].join(';');
    this._emptyEl.innerHTML =
      '<span style="color:#334155;font-size:11px;letter-spacing:.12em">' +
      '尚無情緒足跡 · 繼續傾訴後出現</span>';
    wrap.appendChild(this._emptyEl);

    this.container.appendChild(wrap);
    this._mounted = true;

    this._startLoop();
    this._renderDots();
  }

  // ── SVG 線性漸層定義 ──────────────────────────────────
  _buildDefs() {
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

    const mkLinear = (id, stops) => {
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');
      g.setAttribute('id', id);
      g.setAttribute('x1', '0%'); g.setAttribute('y1', '0%');
      g.setAttribute('x2', '0%'); g.setAttribute('y2', '100%');
      stops.forEach(([offset, color]) => {
        const s = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        s.setAttribute('offset', offset);
        s.setAttribute('stop-color', color);
        g.appendChild(s);
      });
      return g;
    };

    defs.appendChild(mkLinear('wcGradBg', [
      ['0%',   'rgba(30,41,59,0.6)'],
      ['100%', 'rgba(30,41,59,0)'],
    ]));
    defs.appendChild(mkLinear('wcGradFg', [
      ['0%',   'rgba(99,102,241,0.55)'],
      ['65%',  'rgba(99,102,241,0.12)'],
      ['100%', 'rgba(99,102,241,0)'],
    ]));

    this.svg.appendChild(defs);
  }

  _makePath(fill, stroke, opacity) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('fill',         fill);
    p.setAttribute('stroke',       stroke);
    p.setAttribute('stroke-width', '1.5');
    p.setAttribute('opacity',      String(opacity));
    this.svg.insertBefore(p, this._dots || null);
    return p;
  }

  // ── 計算貝茲波形路徑字串 ──────────────────────────────
  //   phase     : 當前時間相位（rAF 累積）
  //   amplitude : 波峰振幅（px）
  //   baseY     : 靜止水位（px）
  //   freq      : 空間頻率係數
  //   biasArr   : 情緒強度陣列（null = 忽略）
  _buildWavePath(phase, amplitude, baseY, freq, biasArr) {
    const W    = this.container.offsetWidth || 360;
    const H    = 160;
    const SEGS = 60;

    const getBias = (x) => {
      if (!biasArr?.length) return 0;
      const ratio = x / W;
      const idx   = Math.min(Math.round(ratio * (biasArr.length - 1)), biasArr.length - 1);
      return ((biasArr[idx] - 3) / 2) * 22; // ±22px
    };

    const yAt = (i) => {
      const x   = (i / SEGS) * W;
      const sin = Math.sin(phase + (i / SEGS) * freq * Math.PI * 2);
      return baseY - amplitude * sin - getBias(x);
    };

    let d = `M 0 ${H}`;
    for (let i = 0; i <= SEGS; i++) {
      const x = (i / SEGS) * W;
      const y = yAt(i);
      if (i === 0) {
        d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
      } else {
        const px  = ((i - 1) / SEGS) * W;
        const cpX = ((px + x) / 2).toFixed(1);
        const py  = yAt(i - 1).toFixed(1);
        d += ` C ${cpX} ${py}, ${cpX} ${y.toFixed(1)}, ${x.toFixed(1)} ${y.toFixed(1)}`;
      }
    }
    d += ` L ${W} ${H} Z`;
    return d;
  }

  // ── rAF 動畫循環 ──────────────────────────────────────
  _startLoop() {
    const intensities = this._extractIntensities();

    const tick = () => {
      if (!this._mounted) return;   // destroy() 後最後一幀安全退出
      this._phase += 0.007;

      // 背景波：慢、振幅大、無資料偏移
      this._bgPath.setAttribute(
        'd', this._buildWavePath(this._phase * 0.55, 20, 115, 0.9, null)
      );
      // 主波：含情緒偏移
      this._fgPath.setAttribute(
        'd', this._buildWavePath(this._phase, 13, 98, 1.1, intensities)
      );

      // 動態更新主波顏色（根據平均強度）
      const avg = intensities.length
        ? intensities.reduce((a, b) => a + b, 0) / intensities.length
        : 3;
      const col = intensityColor(avg);
      this._fgPath.setAttribute('stroke', col.stroke);

      this._raf = requestAnimationFrame(tick);
    };

    this._raf = requestAnimationFrame(tick);
  }

  // ── 情緒強度陣列 ─────────────────────────────────────
  _extractIntensities() {
    return this.records.map(r =>
      r.arousal_level ?? EMOJI_INTENSITY[r.emotion_emoji] ?? 3
    );
  }

  // ── SVG 資料點（emoji + 光環）────────────────────────
  _renderDots() {
    this._dots.innerHTML = '';
    const n = this.records.length;
    if (!n) { this._emptyEl.style.display = 'flex'; return; }
    this._emptyEl.style.display = 'none';

    const W = this.container.offsetWidth || 360;

    this.records.forEach((r, i) => {
      const x  = n > 1 ? (i / (n - 1)) * (W - 28) + 14 : W / 2;
      const lv = r.arousal_level ?? EMOJI_INTENSITY[r.emotion_emoji] ?? 3;
      // y 反映強度：強度高 → 偏上
      const y  = 130 - ((lv / 5) * 72);

      // 光暈
      const halo = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      halo.setAttribute('cx', x.toFixed(1));
      halo.setAttribute('cy', y.toFixed(1));
      halo.setAttribute('r',  '7');
      halo.setAttribute('fill',         'rgba(99,102,241,0.12)');
      halo.setAttribute('stroke',       'rgba(99,102,241,0.45)');
      halo.setAttribute('stroke-width', '1');
      this._dots.appendChild(halo);

      // Emoji 標籤（懸浮於光暈上方）
      const emoji = r.emotion_emoji;
      if (emoji) {
        const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        txt.setAttribute('x',           x.toFixed(1));
        txt.setAttribute('y',           (y - 13).toFixed(1));
        txt.setAttribute('text-anchor', 'middle');
        txt.setAttribute('font-size',   '13');
        txt.textContent = emoji;
        this._dots.appendChild(txt);
      }

      // 日期標籤（底部）
      if (r.date) {
        const dayNum = r.date.slice(-2).replace(/^0/, '');
        const lbl    = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        lbl.setAttribute('x',           x.toFixed(1));
        lbl.setAttribute('y',           '152');
        lbl.setAttribute('text-anchor', 'middle');
        lbl.setAttribute('font-size',   '9');
        lbl.setAttribute('fill',        '#334155');
        lbl.textContent = dayNum;
        this._dots.appendChild(lbl);
      }
    });
  }

  // ── 公開 API ──────────────────────────────────────────

  /** 即時更新資料並重繪資料點 */
  update(records = []) {
    this.records = records;
    this._renderDots();
  }

  /** 銷毀動畫、觸發 GC（離開頁面時呼叫） */
  destroy() {
    this._mounted = false;
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
    // 取得 SVG 內的 canvas（若存在）並釋放 GPU 佔用
    const svgEl = this.container?.querySelector('svg');
    if (svgEl) svgEl.remove();
    if (this.container) this.container.innerHTML = '';
    this.records = [];
  }

  /**
   * 靜態工廠：從 /api/emotion-calendar 取得資料後建立圖表
   * @param {HTMLElement} container
   * @param {{ year:number, month:number, token?:string }} opts
   */
  static async fromAPI(container, { year, month, token } = {}) {
    let records = [];
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(`/api/emotion-calendar?year=${year}&month=${month}`, { headers });
      if (res.ok) {
        const json = await res.json();
        records = json.records || [];
      }
    } catch (e) {
      console.warn('[WaveChart] API fetch failed:', e);
    }
    return new WaveChart(container, { records });
  }
}
