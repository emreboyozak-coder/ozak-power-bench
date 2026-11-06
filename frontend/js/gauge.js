/**
 * Ozak Power - Aerospace Grade Dual-Ring Power Efficiency Gauge
 * Çift halkalı, yüksek çözünürlüklü endüstriyel verimlilik kadranı.
 */
class EfficiencyGauge {
  constructor(arcElementId, valueElementId, peakElementId, deltaElementId, outerTrackId) {
    this.arc = document.getElementById(arcElementId);
    this.valEl = document.getElementById(valueElementId);
    this.peakEl = document.getElementById(peakElementId);
    this.deltaEl = document.getElementById(deltaElementId || "kioskGaugeDelta");
    this.outerTrack = document.getElementById(outerTrackId || "kioskOuterTrack");
    this.targetEff = 90.0;
    this.circumference = 640.88; // 2 * PI * 102 (r=102)
    this.lastEff = 0.0;
  }

  setTargetEfficiency(target) {
    this.targetEff = target || 90.0;
    const catEl = document.getElementById("gaugeCatTarget");
    if (catEl) catEl.innerText = `%${this.targetEff.toFixed(0)}`;
  }

  update(efficiency, peakEfficiency) {
    const eff = Math.max(0.0, Math.min(100.0, efficiency));
    
    // 1. Sayısal Metin ve Neon Işıltı Güncelleme
    if (this.valEl) {
      this.valEl.innerText = eff.toFixed(1) + ' %';
      
      if (eff >= 87.0) {
        this.valEl.className = "text-5xl lg:text-6xl font-black tracking-tight text-emerald-400 font-mono drop-shadow-[0_0_25px_rgba(16,185,129,0.5)] tabular-nums";
      } else if (eff >= 82.0) {
        this.valEl.className = "text-5xl lg:text-6xl font-black tracking-tight text-cyan-400 font-mono drop-shadow-[0_0_25px_rgba(6,182,212,0.5)] tabular-nums";
      } else if (eff >= 75.0) {
        this.valEl.className = "text-5xl lg:text-6xl font-black tracking-tight text-amber-300 font-mono drop-shadow-[0_0_20px_rgba(251,191,36,0.4)] tabular-nums";
      } else {
        this.valEl.className = "text-5xl lg:text-6xl font-black tracking-tight text-rose-400 font-mono drop-shadow-[0_0_25px_rgba(225,29,72,0.5)] tabular-nums";
      }
    }

    // 2. Pik Değer
    if (this.peakEl && peakEfficiency !== undefined) {
      this.peakEl.innerText = peakEfficiency.toFixed(1) + ' %';
    }

    // 3. Canlı Delta Kıyaslama Rozeti
    if (this.deltaEl) {
      if (eff > 0.1) {
        const delta = eff - this.targetEff;
        const sign = delta >= 0 ? "+" : "";
        if (delta >= 0.0) {
          this.deltaEl.innerHTML = `
            <span class="text-slate-400 text-[10px]">KATALOG: %${this.targetEff.toFixed(0)}</span>
            <span class="text-slate-600">|</span>
            <span class="text-emerald-400 font-black">▲ ${sign}${delta.toFixed(1)}%</span>
          `;
          this.deltaEl.className = "mt-1.5 inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono font-bold bg-emerald-950/70 border border-emerald-500/50 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.25)]";
        } else if (delta >= -3.0) {
          this.deltaEl.innerHTML = `
            <span class="text-slate-400 text-[10px]">KATALOG: %${this.targetEff.toFixed(0)}</span>
            <span class="text-slate-600">|</span>
            <span class="text-cyan-300 font-black">● ${delta.toFixed(1)}%</span>
          `;
          this.deltaEl.className = "mt-1.5 inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono font-bold bg-cyan-950/70 border border-cyan-500/50 text-cyan-300 shadow-[0_0_15px_rgba(6,182,212,0.25)]";
        } else {
          this.deltaEl.innerHTML = `
            <span class="text-slate-400 text-[10px]">KATALOG: %${this.targetEff.toFixed(0)}</span>
            <span class="text-slate-600">|</span>
            <span class="text-amber-400 font-black">▼ ${delta.toFixed(1)}%</span>
          `;
          this.deltaEl.className = "mt-1.5 inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono font-bold bg-amber-950/70 border border-amber-500/50 text-amber-300 shadow-[0_0_15px_rgba(245,158,11,0.25)]";
        }
      } else {
        this.deltaEl.innerHTML = `
          <span class="text-slate-400 text-[10px]">KATALOG: %${this.targetEff.toFixed(0)}</span>
          <span class="text-slate-600">|</span>
          <span class="text-slate-500 font-bold">Beklemede</span>
        `;
        this.deltaEl.className = "mt-1.5 inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono font-bold bg-[#0d1322] border border-slate-800 text-slate-400";
      }
    }

    // 4. İç Halka Neon Yay Çizgisini Güncelleme (strokeDashoffset)
    if (this.arc) {
      const offset = this.circumference - (eff / 100.0) * this.circumference;
      this.arc.style.strokeDashoffset = offset;
    }

    this.lastEff = eff;
  }
}

window.EfficiencyGauge = EfficiencyGauge;
