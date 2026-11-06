/**
 * Son 60 Saniyelik Kesintisiz Canvas Zaman Akış Grafiği
 */
class TelemetryTrendChart {
  constructor(canvasId, maxPoints = 80) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.maxPoints = maxPoints;

    this.effHistory = new Array(maxPoints).fill(95.0);
    this.pinHistory = new Array(maxPoints).fill(90.0);
    this.poutHistory = new Array(maxPoints).fill(85.0);
    this.moduleTestResult = null;

    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    if (!this.canvas) return;
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.ctx.resetTransform();
    this.ctx.scale(dpr, dpr);
    this.render();
  }

  addData(efficiency, pin, pout) {
    this.effHistory.push(efficiency);
    if (this.effHistory.length > this.maxPoints) this.effHistory.shift();

    this.pinHistory.push(pin);
    if (this.pinHistory.length > this.maxPoints) this.pinHistory.shift();

    this.poutHistory.push(pout);
    if (this.poutHistory.length > this.maxPoints) this.poutHistory.shift();

    this.render();
  }

  showModuleTest(result) {
    const measurements = [...(result.measurements || [])];
    if (result.hold) measurements.push({ ...result.hold, fraction: 1, label: 'Bekleme' });
    this.moduleTestResult = { ...result, chartMeasurements: measurements };
    const title = document.getElementById('trendChartTitle');
    const windowLabel = document.getElementById('trendChartWindow');
    const footer = document.getElementById('trendChartFooter');
    const testLegend = document.getElementById('testChartLegend');
    const liveLegendIds = ['trendLegendEfficiency', 'trendLegendPin', 'trendLegendPout'];
    if (title) title.lastChild.textContent = ` YUVA ${result.slot} YÜK TESTİ`;
    if (windowLabel) windowLabel.textContent = `Hedef ${Number(result.target_power_w || 10).toFixed(1)} W`;
    if (footer) footer.textContent = 'Yük akımı kademesine göre ölçülen çıkış gücü';
    if (testLegend) testLegend.classList.remove('hidden');
    liveLegendIds.forEach(id => document.getElementById(id)?.classList.add('hidden'));
    this.render();
  }

  showLiveTrend() {
    this.moduleTestResult = null;
    const title = document.getElementById('trendChartTitle');
    const windowLabel = document.getElementById('trendChartWindow');
    const footer = document.getElementById('trendChartFooter');
    const testLegend = document.getElementById('testChartLegend');
    const liveLegendIds = ['trendLegendEfficiency', 'trendLegendPin', 'trendLegendPout'];
    if (title) title.lastChild.textContent = ' CANLI VERİMLİLİK AKIŞI';
    if (windowLabel) windowLabel.textContent = '60 saniye gerçek zamanlı';
    if (footer) footer.textContent = 'Zaman serisi kararlılık telemetrisi';
    if (testLegend) testLegend.classList.add('hidden');
    liveLegendIds.forEach(id => document.getElementById(id)?.classList.remove('hidden'));
    this.render();
  }

  render() {
    if (!this.canvas || !this.ctx) return;
    const rect = this.canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    if (w <= 0 || h <= 0) return;

    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);

    if (this.moduleTestResult) {
      this.renderModuleTest(w, h);
      return;
    }

    // Kılavuz Izgarası ve Eksen Etiketleri
    ctx.strokeStyle = '#161e2e';
    ctx.lineWidth = 1;
    ctx.font = '10px monospace';
    ctx.fillStyle = '#475569';

    const numRows = 4;
    for (let i = 0; i <= numRows; i++) {
      const y = (h / numRows) * i;
      ctx.beginPath();
      ctx.moveTo(35, y);
      ctx.lineTo(w - 35, y);
      ctx.stroke();

      // Sol Eksen: Verim % (80% - 100%)
      const effVal = 100 - (i * (20 / numRows));
      ctx.textAlign = 'left';
      ctx.fillText(effVal.toFixed(0) + '%', 4, Math.max(10, Math.min(h - 2, y + 3)));

      // Sağ Eksen: Güç W (0W - 150W)
      const pwrVal = 150 - (i * (150 / numRows));
      ctx.textAlign = 'right';
      ctx.fillText(pwrVal.toFixed(0) + 'W', w - 4, Math.max(10, Math.min(h - 2, y + 3)));
    }

    // 1. Verimlilik Eğrisi (Yeşil) - 80% ile 100% aralığı
    this.drawLine(
      this.effHistory,
      80, 100,
      '#10b981',
      'rgba(16, 185, 129, 0.12)',
      w, h, 2.5
    );

    // 2. Giriş Gücü P_in (Amber) - 0W ile 150W aralığı
    this.drawLine(
      this.pinHistory,
      0, 150,
      '#f59e0b',
      null,
      w, h, 2
    );

    // 3. Çıkış Gücü P_out (Cyan) - 0W ile 150W aralığı
    this.drawLine(
      this.poutHistory,
      0, 150,
      '#06b6d4',
      null,
      w, h, 2
    );
  }

  renderModuleTest(w, h) {
    const ctx = this.ctx;
    const result = this.moduleTestResult || {};
    const points = (result.chartMeasurements || result.measurements || [])
      .filter(point => Number.isFinite(Number(point.output_power)));
    const target = Number(result.target_power_w) || 10;
    const yMax = Math.max(12, Math.ceil(target * 1.2));
    const left = 44;
    const right = w - 14;
    const top = 22;
    const bottom = h - 30;
    const plotHeight = bottom - top;

    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#64748b';
    for (let i = 0; i <= 4; i++) {
      const value = yMax - (yMax * i / 4);
      const y = top + plotHeight * i / 4;
      ctx.strokeStyle = '#253047';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(right, y);
      ctx.stroke();
      ctx.fillText(`${value.toFixed(0)} W`, 3, y);
    }

    const targetY = bottom - Math.min(target, yMax) / yMax * plotHeight;
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(left, targetY);
    ctx.lineTo(right, targetY);
    ctx.stroke();
    ctx.restore();

    if (points.length === 0) {
      ctx.fillStyle = '#94a3b8';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const idleText = result.no_load
        ? `Yüksüz ${Number(result.no_load.output_voltage).toFixed(2)} V · yük kademesi ölçülmedi`
        : (result.message || 'Yük ölçümü bulunmuyor');
      ctx.fillText(idleText, (left + right) / 2, (top + bottom) / 2);
      return;
    }

    const xFor = index => points.length === 1
      ? (left + right) / 2
      : left + (right - left) * index / (points.length - 1);
    ctx.strokeStyle = '#22d3ee';
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    points.forEach((point, index) => {
      const x = xFor(index);
      const power = Number(point.output_power);
      const y = bottom - Math.max(0, Math.min(yMax, power)) / yMax * plotHeight;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    points.forEach((point, index) => {
      const x = xFor(index);
      const power = Number(point.output_power);
      const y = bottom - Math.max(0, Math.min(yMax, power)) / yMax * plotHeight;
      const percent = Math.round(Number(point.fraction ?? (index + 1) / points.length) * 100);
      ctx.fillStyle = '#22d3ee';
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#cbd5e1';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(`${power.toFixed(1)} W`, x, y - 6);
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#94a3b8';
      ctx.fillText(point.label || `${percent}%`, x, bottom + 7);
    });

    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillStyle = result.status === 'passed' ? '#34d399' : '#fbbf24';
    ctx.fillText(result.status === 'passed' ? 'GEÇTİ' : 'TEST SONUCU', right, 3);
  }

  drawLine(data, minVal, maxVal, strokeColor, fillColor, w, h, lineWidth) {
    const ctx = this.ctx;
    const paddingX = 40;
    const effectiveWidth = w - (paddingX * 2);
    const step = effectiveWidth / (data.length - 1);

    ctx.beginPath();
    data.forEach((val, i) => {
      const norm = (val - minVal) / (maxVal - minVal);
      const clampedNorm = Math.max(0, Math.min(1, norm));
      const y = h - (clampedNorm * h);
      const x = paddingX + (i * step);

      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = lineWidth;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();

    if (fillColor) {
      ctx.lineTo(paddingX + effectiveWidth, h);
      ctx.lineTo(paddingX, h);
      ctx.closePath();
      ctx.fillStyle = fillColor;
      ctx.fill();
    }
  }
}
