/**
 * Ozak Power - Verimlilik vs Yük Akımı Eğrisi (Efficiency Curve Chart)
 * Yük akımına karşılık ölçülen verimlilik noktalarını canlı çizen yüksek performanslı Canvas grafiği.
 */
class SweepCurveChart {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
    this.points = []; // [{ i_out, efficiency, p_loss }]
    this.targetEff = 90.0;
    this.dutModel = "OZP50S48SS05A";

    this._setupResize();
  }

  _setupResize() {
    if (!this.canvas) return;
    const resize = () => {
      this.resizeAndDraw();
    };
    window.addEventListener('resize', resize);
    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver(resize);
      this.resizeObserver.observe(this.canvas.parentElement);
    }
    setTimeout(resize, 150);
  }

  resizeAndDraw() {
    if (!this.canvas) return;
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    if (this.ctx) {
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      this.ctx.scale(dpr, dpr);
    }
    this.draw();
  }

  setTargetEff(eff, model) {
    this.targetEff = eff || 90.0;
    if (model) this.dutModel = model;
    this.draw();
  }

  setPoints(points) {
    this.points = points || [];
    this.draw();
  }

  clear() {
    this.points = [];
    this.draw();
  }

  draw() {
    if (!this.ctx || !this.canvas) return;
    const rect = this.canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    const ctx = this.ctx;

    if (w <= 0 || h <= 0) return;

    ctx.clearRect(0, 0, w, h);

    // Padding
    const padL = 55;
    const padR = 30;
    const padT = 35;
    const padB = 55;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;

    if (plotW <= 0 || plotH <= 0) return;

    // Eksen Aralıkları (0.4A - 4.0A | %10 - %100 Lineer Matris)
    const minI = 0;
    const maxI = Math.max(20, ...this.points.map(pt => pt.p_target || pt.p_out || 0));
    const minEff = 60.0;
    const maxEff = 100.0;

    // Arka Plan Izgarası
    ctx.strokeStyle = "rgba(51, 65, 85, 0.4)";
    ctx.lineWidth = 1;
    ctx.font = "11px monospace";
    ctx.fillStyle = "#64748b";

    // Y Eksen Çizgileri (Verim %)
    const ySteps = [60, 70, 80, 85, 90, 95, 100];
    ySteps.forEach(val => {
      const y = padT + plotH - ((val - minEff) / (maxEff - minEff)) * plotH;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();

      ctx.fillText(`${val}%`, padL - 40, y + 4);
    });

    // X Eksen Çizgileri (0.4A'dan 4.0A'ya %10 Adımlarla - 10 Nokta)
    const xSteps = Array.from({ length: 5 }, (_, i) => maxI * i / 4);
    xSteps.forEach(val => {
      const x = padL + ((val - minI) / (maxI - minI)) * plotW;
      const pct = Math.round((val / maxI) * 100);
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + plotH);
      ctx.stroke();

      ctx.font = "bold 10px monospace";
      ctx.fillStyle = "#cbd5e1";
      ctx.fillText(`${val.toFixed(1)}W`, x - 12, padT + plotH + 16);
      ctx.font = "9px monospace";
      ctx.fillStyle = "#64748b";
      ctx.fillText(`%${pct}`, x - 9, padT + plotH + 28);
    });

    // Eksen İsimleri
    ctx.fillStyle = "#94a3b8";
    ctx.font = "bold 11px monospace";
    ctx.fillText("VERİMLİLİK (%)", padL, padT - 15);
    ctx.save();
    ctx.textAlign = "center";
    ctx.fillText("ÇIKIŞ GÜCÜ (W)", padL + plotW / 2, padT + plotH + 51);
    ctx.restore();

    // Katalog Nominal Verim Referans Çizgisi (Kırmızı / Kesikli)
    const targetY = padT + plotH - ((this.targetEff - minEff) / (maxEff - minEff)) * plotH;
    ctx.save();
    ctx.setLineDash([6, 5]);
    ctx.strokeStyle = "rgba(225, 29, 72, 0.9)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(padL, targetY);
    ctx.lineTo(padL + plotW, targetY);
    ctx.stroke();
    ctx.restore();

    ctx.fillStyle = "#e11d48";
    ctx.font = "bold 11px monospace";
    ctx.fillText(`Katalog Nominal Hedefi: %${this.targetEff.toFixed(0)}`, padL + plotW - 180, targetY - 7);

    if (this.points.length === 0) {
      // Bilgi Mesajı
      ctx.fillStyle = "#64748b";
      ctx.font = "13px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Güç adımlı verimlilik taraması başlatıldığında eğri burada canlı oluşacaktır.", padL + plotW / 2, padT + plotH / 2);
      ctx.textAlign = "left";
      return;
    }

    // Koordinat Dönüştürücü (0.4A - 4.0A sınırlarına taşma korumalı)
    const getX = (i) => {
      const val = Math.max(minI, Math.min(maxI, parseFloat(i) || minI));
      return padL + ((val - minI) / (maxI - minI)) * plotW;
    };
    const getY = (eff) => {
      const val = Math.max(minEff, Math.min(maxEff, parseFloat(eff) || minEff));
      return padT + plotH - ((val - minEff) / (maxEff - minEff)) * plotH;
    };

    // 1. Fiziksel Güç Elektroniği Kayıp Modeli (P_loss = a*I^2 + b*I + c) Regresyonu
    const curvePath = this.points.map(pt => ({
      x: getX(pt.p_target || pt.p_out),
      y: getY(pt.efficiency)
    }));

    // 2. Alan Doldurma (Pürüzsüz Gradyan Altı)
    ctx.save();
    const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    grad.addColorStop(0, "rgba(225, 29, 72, 0.45)");
    grad.addColorStop(0.5, "rgba(6, 182, 212, 0.2)");
    grad.addColorStop(1, "rgba(16, 185, 129, 0.0)");

    ctx.beginPath();
    ctx.moveTo(curvePath[0].x, padT + plotH);
    ctx.lineTo(curvePath[0].x, curvePath[0].y);
    for (let i = 1; i < curvePath.length; i++) {
      ctx.lineTo(curvePath[i].x, curvePath[i].y);
    }
    ctx.lineTo(curvePath[curvePath.length - 1].x, padT + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 3. Pürüzsüz Fiziksel Eğri Çizgisi (Neon Turkuaz)
    ctx.beginPath();
    ctx.moveTo(curvePath[0].x, curvePath[0].y);
    for (let i = 1; i < curvePath.length; i++) {
      ctx.lineTo(curvePath[i].x, curvePath[i].y);
    }
    ctx.strokeStyle = "#06b6d4";
    ctx.lineWidth = 3.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.shadowColor = "rgba(6, 182, 212, 0.6)";
    ctx.shadowBlur = 10;
    ctx.stroke();
    ctx.restore();

    // 4. Gerçek Ham Ölçüm Noktaları (Daireler ve Değer Etiketleri)
    this.points.forEach((pt, idx) => {
      const px = getX(pt.p_target || pt.p_out);
      const py = getY(pt.efficiency);

      ctx.beginPath();
      ctx.arc(px, py, 5, 0, 2 * Math.PI);
      ctx.fillStyle = pt.efficiency >= this.targetEff ? "#10b981" : "#e11d48";
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2.5;
      ctx.stroke();

      // Değer etiketi (% Verim)
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 10px monospace";
      const effLabel = `${pt.efficiency.toFixed(1)}%`;
      const isAlt = (idx % 2 === 1);
      ctx.fillText(effLabel, px - 16, isAlt ? py + 18 : py - 10);
    });

    ctx.restore();
  }

  _fitPhysicalLossModel(points) {
    if (!points || points.length < 3) return null;
    let sumX = 0, sumX2 = 0, sumX3 = 0, sumX4 = 0;
    let sumY = 0, sumXY = 0, sumX2Y = 0;
    const n = points.length;

    for (let i = 0; i < n; i++) {
      const x = points[i].i_out || points[i].i_target || 0.4;
      const y = points[i].p_loss !== undefined ? points[i].p_loss : Math.max(0.1, points[i].p_in - points[i].p_out);
      const x2 = x * x;
      sumX += x;
      sumX2 += x2;
      sumX3 += x2 * x;
      sumX4 += x2 * x2;
      sumY += y;
      sumXY += x * y;
      sumX2Y += x2 * y;
    }

    const m = [
      [sumX4, sumX3, sumX2, sumX2Y],
      [sumX3, sumX2, sumX,  sumXY],
      [sumX2, sumX,  n,     sumY]
    ];

    for (let i = 0; i < 3; i++) {
      let maxRow = i;
      for (let k = i + 1; k < 3; k++) {
        if (Math.abs(m[k][i]) > Math.abs(m[maxRow][i])) maxRow = k;
      }
      const tmp = m[i]; m[i] = m[maxRow]; m[maxRow] = tmp;
      const pivot = m[i][i];
      if (Math.abs(pivot) < 1e-12) return null;
      for (let j = i; j <= 3; j++) m[i][j] /= pivot;
      for (let k = 0; k < 3; k++) {
        if (k !== i) {
          const factor = m[k][i];
          for (let j = i; j <= 3; j++) m[k][j] -= factor * m[i][j];
        }
      }
    }

    return { a: m[0][3], b: m[1][3], c: m[2][3] };
  }

  _evalModel(model, i, vNom = 5.0) {
    const ploss = Math.max(0.15, model.a * i * i + model.b * i + model.c);
    const pout = vNom * i;
    return (pout / (pout + ploss)) * 100.0;
  }
}

window.SweepCurveChart = SweepCurveChart;
