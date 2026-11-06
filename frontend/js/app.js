/**
 * Ozak Power - DC-DC Telemetri & Verimlilik Kiosk İstemcisi
 * Executive Dark Tech: Canlı Test Bench, Sweep Engine, Ürün Kataloğu ve Kiosk Kontrolleri
 */

let isPsuActive = true;
let isLoadActive = true;
let targetCurrent = 2.0;
let ws = null;
let reconnectTimer = null;
let currentDUT = null;
let systemMode = null;
let fullCatalog = {};
let powerFamilies = [];
let sweepPollTimer = null;
let activeMainTab = "bench"; // "bench", "sweep", "catalog"

// Global Grafik Nesneleri
let gaugeInstance = null;
let trendChartInstance = null;
let sweepChartInstance = null;

// DOM Elemanları
const kioskEffVal = document.getElementById("kioskEffVal");
const kioskPeakEff = document.getElementById("kioskPeakEff");
const kioskPin = document.getElementById("kioskPin");
const kioskVinTop = document.getElementById("kioskVinTop");
const kioskIinTop = document.getElementById("kioskIinTop");
const kioskPout = document.getElementById("kioskPout");
const kioskVout = document.getElementById("kioskVout");
const kioskIout = document.getElementById("kioskIout");
const kioskPloss = document.getElementById("kioskPloss");
const thermalStatusText = document.getElementById("thermalStatusText");
const connectionDot = document.getElementById("connectionDot");
const connectionStatusText = document.getElementById("connectionStatusText");
const modeText = document.getElementById("modeText");

// Kontrol Barı DOM Elemanları
const btnPsuToggle = document.getElementById("btnPsuToggle");
const psuToggleDot = document.getElementById("psuToggleDot");
const psuToggleText = document.getElementById("psuToggleText");
const btnLoadToggle = document.getElementById("btnLoadToggle");
const loadToggleDot = document.getElementById("loadToggleDot");
const loadToggleText = document.getElementById("loadToggleText");
const kioskSliderVal = document.getElementById("kioskSliderVal");
const kioskSlider = document.getElementById("kioskSlider");

// DUT Rozetleri & İki Aşamalı Seçici
const familySelect = document.getElementById("familySelect");
const dutSelect = document.getElementById("dutSelect");
const dutCatalogEffBadge = document.getElementById("dutCatalogEffBadge");
const dutComparisonBadge = document.getElementById("dutComparisonBadge");
const dutPowerBadge = document.getElementById("dutPowerBadge");
const dutVinBadge = document.getElementById("dutVinBadge");
const gaugeDutLabel = document.getElementById("gaugeDutLabel");
const vinBandMin = document.getElementById("vinBandMin");
const vinBandNom = document.getElementById("vinBandNom");
const vinBandMax = document.getElementById("vinBandMax");

// Sweep DOM Elemanları
const btnStartSweep = document.getElementById("btnStartSweep");
const btnStopSweep = document.getElementById("btnStopSweep");
const sweepProgressBar = document.getElementById("sweepProgressBar");
const sweepProgressText = document.getElementById("sweepProgressText");
const sweepStatusBadge = document.getElementById("sweepStatusBadge");

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

  try {
    ws = new WebSocket(wsUrl);
  } catch (err) {
    console.warn("WebSocket bağlantısı açılamadı:", err);
    return;
  }

  ws.onopen = () => {
    console.log("[WS] Bağlantı kuruldu.");
    if (connectionDot) connectionDot.className = "w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse";
    if (connectionStatusText) {
      connectionStatusText.innerText = "CANLI TELEMETRİ";
      connectionStatusText.className = "text-emerald-400 font-bold";
    }
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      updateTelemetryUI(data);
    } catch (err) {
      console.error("[WS] Veri işleme hatası:", err);
    }
  };

  ws.onclose = () => {
    if (numericAnimationId !== null) cancelAnimationFrame(numericAnimationId);
    numericAnimationId = null;
    displayedTelemetryNumbers = null;
    if (connectionDot) connectionDot.className = "w-2.5 h-2.5 rounded-full bg-rose-500";
    if (connectionStatusText) {
      connectionStatusText.innerText = "BAĞLANTI KESİLDİ";
      connectionStatusText.className = "text-rose-500 font-bold";
    }
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(initWebSocket, 2000);
  };
}

const slotTestOutcomes = new Map();
let latestSlotState = { active_slot: null, test_active: false };

function updateActiveSlotUI(data) {
  latestSlotState = data;
  const slot = Number(data.active_slot);
  const valid = Number.isInteger(slot) && slot >= 1 && slot <= 5;
  const status = document.getElementById("activeSlotStatus");
  const description = valid
    ? `Yuva ${slot} · ${data.test_active ? "Test ediliyor" : "Röle seçili"}`
    : "Aktif yuva yok";
  if (status && status.innerText !== description) status.innerText = description;
  for (let i = 1; i <= 5; i++) {
    const card = document.getElementById(`slotIndicator${i}`);
    if (!card) continue;
    const active = valid && i === slot;
    const outcome = slotTestOutcomes.get(i);
    const testing = active && data.test_active;
    const base = "aspect-square w-full flex flex-col items-center justify-center rounded-xl text-center ";
    card.className = testing || (active && !outcome)
      ? "aspect-square w-full flex flex-col items-center justify-center rounded-xl border-2 border-cyan-400 bg-cyan-950/70 text-center text-cyan-200 shadow-[0_0_18px_rgba(34,211,238,0.3)]"
      : outcome === "working" ? base + "border-2 border-emerald-400 bg-emerald-950/70 text-emerald-200"
      : outcome === "failed" ? base + "border-2 border-red-400 bg-red-950/70 text-red-200"
      : outcome === "uncertain" ? base + "border-2 border-amber-400 bg-amber-950/70 text-amber-200"
      : "aspect-square w-full flex flex-col items-center justify-center rounded-xl border border-slate-700 bg-slate-950/60 text-center text-slate-500";
    const state = card.querySelector("[data-slot-state]");
    if (state) state.innerText = testing ? "TESTTE"
      : outcome === "working" ? "ÇALIŞIYOR"
      : outcome === "failed" ? "BOŞ / BAŞARISIZ"
      : outcome === "uncertain" ? "BELİRSİZ"
      : active ? "SEÇİLİ" : "KAPALI";
    if (active) card.setAttribute("aria-current", "true");
    else card.removeAttribute("aria-current");
  }
}

let numericAnimationId = null;
let displayedTelemetryNumbers = null;

function renderTelemetryNumbers(values) {
  const fields = [
    [kioskEffVal, "eff", 1, " %"], [kioskPeakEff, "peakEff", 1, " %"],
    [kioskPin, "pIn", 3, ""], [kioskVinTop, "vIn", 3, " V"],
    [kioskIinTop, "iIn", 3, " A"], [kioskPout, "pOut", 3, ""],
    [kioskVout, "vOut", 3, " V"], [kioskIout, "iOut", 3, " A"],
    [kioskPloss, "pLoss", 3, " W"]
  ];
  for (const [element, key, decimals, unit] of fields) {
    if (!element) continue;
    const text = values[key].toFixed(decimals) + unit;
    if (element.textContent !== text) element.textContent = text;
  }
  if (gaugeInstance) gaugeInstance.update(values.eff, values.peakEff);
}

function updateTelemetryNumbers(values, simulation) {
  if (numericAnimationId !== null) cancelAnimationFrame(numericAnimationId);
  numericAnimationId = null;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!simulation || !displayedTelemetryNumbers || reducedMotion) {
    displayedTelemetryNumbers = { ...values };
    renderTelemetryNumbers(values);
    return;
  }
  const from = { ...displayedTelemetryNumbers };
  const started = performance.now();
  const animate = (now) => {
    const t = Math.min(1, Math.max(0, (now - started) / 300));
    const ease = t * t * (3 - 2 * t);
    const interpolated = {};
    for (const key of Object.keys(values)) interpolated[key] = from[key] + (values[key] - from[key]) * ease;
    displayedTelemetryNumbers = interpolated;
    renderTelemetryNumbers(interpolated);
    numericAnimationId = t < 1 ? requestAnimationFrame(animate) : null;
  };
  numericAnimationId = requestAnimationFrame(animate);
}

function updateTelemetryUI(data) {
  if (!data) return;
  if (data.mode) systemMode = data.mode;
  updateActiveSlotUI(data);

  const eff = data.efficiency !== undefined ? data.efficiency : 0.0;
  const pIn = data.input ? data.input.p_total : 0.0;
  const vIn = data.input ? data.input.v_total : 0.0;
  const iIn = data.input ? data.input.i_series : 0.0;
  const pOut = data.output ? data.output.p_out : 0.0;
  const vOut = data.output ? data.output.v_out : 0.0;
  const iOut = data.output ? data.output.i_out : 0.0;
  const pLoss = data.p_loss !== undefined ? data.p_loss : 0.0;
  const peakEff = data.peak_efficiency !== undefined ? data.peak_efficiency : 0.0;

  updateTelemetryNumbers({ eff, peakEff, pIn, vIn, iIn, pOut, vOut, iOut, pLoss }, data.mode === "SIMULATION");

  // Top Bar Kıyaslama Rozeti
  if (currentDUT && dutComparisonBadge) {
    const typ = currentDUT.typ_eff || 90.0;
    if (eff > 0.1) {
      const diff = eff - typ;
      const sign = diff >= 0 ? "+" : "";
      if (diff >= 0.0) {
        dutComparisonBadge.innerHTML = `<span class="text-emerald-400 font-bold">▲ ${sign}${diff.toFixed(1)}% (Katalog Üstü)</span>`;
      } else if (diff >= -3.0) {
        dutComparisonBadge.innerHTML = `<span class="text-cyan-300 font-bold">● ${diff.toFixed(1)}% (Nominal Bant)</span>`;
      } else {
        dutComparisonBadge.innerHTML = `<span class="text-amber-400 font-bold">▼ ${diff.toFixed(1)}% (Hafif/Ağır Yük)</span>`;
      }
    } else {
      dutComparisonBadge.innerHTML = `<span class="text-slate-500 font-bold">Beklemede</span>`;
    }
  }

  // 3 Noktalı Laboratuvar Voltaj Seçici Butonlarını ve Rozetini Giriş Gerilimine Göre Senkronize Et
  const b18 = document.getElementById("vinBand18");
  const b48 = document.getElementById("vinBand48");
  const b72 = document.getElementById("vinBand72");
  const psuCalibText = document.getElementById("psuCalibText");
  const activeCls = "px-2.5 py-1 rounded cursor-pointer text-amber-300 font-bold bg-amber-500/20 shadow-sm border border-amber-500/40 transition";
  const inactiveCls = "px-2.5 py-1 rounded cursor-pointer text-slate-400 hover:text-white transition";
  if (vIn < 30.0) {
    if (b18) b18.className = activeCls;
    if (b48) b48.className = inactiveCls;
    if (b72) b72.className = inactiveCls;
  } else if (vIn < 60.0) {
    if (b18) b18.className = inactiveCls;
    if (b48) b48.className = activeCls;
    if (b72) b72.className = inactiveCls;
  } else {
    if (b18) b18.className = inactiveCls;
    if (b48) b48.className = inactiveCls;
    if (b72) b72.className = activeCls;
  }
  if (psuCalibText) {
    psuCalibText.innerHTML = `&bull; ${vIn.toFixed(3)}V UDP6731 (Canlı 4-Wire Sense & SCPI)`;
  }

  // Mod ve Donanım Rozetleri Güncelleme (Çift Gerçek Donanım: UDP6731 + UTL8511)
  const isHw = data.mode === "HARDWARE";
  const psuConnected = !!data.hmp_connected;
  const utlConnected = !!data.utl_connected;
  const kioskLoadStatusText = document.getElementById("kioskLoadStatusText");
  const modeBtn = document.getElementById("modeToggleBtn");

  if (isHw) {
    if (psuConnected && utlConnected) {
      if (modeText) modeText.innerText = "TEST MODU";
      if (modeBtn) {
        modeBtn.className = "flex items-center gap-2 bg-gradient-to-r from-emerald-600 to-teal-700 hover:from-emerald-500 hover:to-teal-600 text-white px-3.5 py-1.5 rounded-xl font-bold transition shadow-[0_0_20px_rgba(16,185,129,0.4)] border border-emerald-500/60";
      }
      if (kioskLoadStatusText) {
        kioskLoadStatusText.innerHTML = `<span class="text-emerald-400 font-mono">● 4-Wire Kelvin Sense &bull; UTL8511 (${data.load_port || "COM11"} Aktif)</span>`;
      }
    } else if (psuConnected && !utlConnected) {
      if (modeText) modeText.innerText = "TEST · YÜK BAĞLI DEĞİL";
      if (modeBtn) {
        modeBtn.className = "flex items-center gap-2 bg-gradient-to-r from-emerald-600 to-teal-700 hover:from-emerald-500 hover:to-teal-600 text-white px-3.5 py-1.5 rounded-xl font-bold transition shadow-[0_0_20px_rgba(16,185,129,0.4)] border border-emerald-500/60";
      }
      if (kioskLoadStatusText) {
        kioskLoadStatusText.innerHTML = `<span class="text-emerald-400 font-mono">● 5.00V Regüle Çıkış &bull; Ozak Power DUT Aktif</span>`;
      }
    } else if (!psuConnected && utlConnected) {
      if (modeText) modeText.innerText = "TEST · PSU BAĞLI DEĞİL";
      if (modeBtn) {
        modeBtn.className = "flex items-center gap-2 bg-gradient-to-r from-amber-600 to-yellow-700 text-white px-3.5 py-1.5 rounded-xl font-bold transition border border-amber-500/60";
      }
    } else {
      if (modeText) modeText.innerText = "TEST · DONANIM BAĞLI DEĞİL";
      if (modeBtn) {
        modeBtn.className = "flex items-center gap-2 bg-gradient-to-r from-rose-600 to-amber-700 hover:from-rose-500 hover:to-amber-600 text-white px-3.5 py-1.5 rounded-xl font-bold transition shadow-[0_0_20px_rgba(225,29,72,0.4)] border border-rose-500/60 animate-pulse";
      }
      if (kioskLoadStatusText) {
        kioskLoadStatusText.innerHTML = `<span class="text-rose-400 font-bold font-mono animate-pulse">⚠️ USB KABLOLARI KONTROL EDİN</span>`;
      }
    }
  } else {
    if (modeText) modeText.innerText = "SİMÜLASYON";
    if (modeBtn) {
      modeBtn.className = "flex items-center gap-2 bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-white px-3.5 py-1.5 rounded-xl font-bold transition shadow-[0_0_20px_rgba(6,182,212,0.4)] border border-cyan-500/60";
    }
    if (kioskLoadStatusText) {
      kioskLoadStatusText.innerHTML = `<span class="text-cyan-400 font-mono">4-Wire Kelvin Sense &bull; Simülasyon</span>`;
    }
  }

  // Çift Halkalı Aerospace Kadranı Güncelle

  // Canlı Trend Grafiğine Ekle
  if (trendChartInstance && activeMainTab === "bench") {
    trendChartInstance.addData(eff, pIn, pOut);
  }

  // Termal Durum Rozeti
  if (thermalStatusText) {
    if (pLoss < 5.0) {
      thermalStatusText.innerText = "GÜVENLİ (DÜŞÜK ISI)";
      thermalStatusText.className = "text-[10px] font-bold text-emerald-400 bg-emerald-950/70 border border-emerald-700/60 px-2.5 py-0.5 rounded-full shadow-[0_0_12px_rgba(16,185,129,0.2)]";
    } else if (pLoss < 10.0) {
      thermalStatusText.innerText = "ORTA ISI (NORMAL)";
      thermalStatusText.className = "text-[10px] font-bold text-amber-400 bg-amber-950/70 border border-amber-700/60 px-2.5 py-0.5 rounded-full shadow-[0_0_12px_rgba(245,158,11,0.2)]";
    } else {
      thermalStatusText.innerText = "YÜKSEK ISI (DİKKAT)";
      thermalStatusText.className = "text-[10px] font-bold text-rose-400 bg-rose-950/70 border border-rose-700/60 px-2.5 py-0.5 rounded-full shadow-[0_0_15px_rgba(225,29,72,0.3)]";
    }
  }
}

// DUT Kataloğunu Getir ve İki Aşamalı Seçiciyi Doldur
async function loadDUTCatalog() {
  try {
    const res = await fetch("/api/dut/catalog");
    const data = await res.json();
    if (!data.catalog) return;

    fullCatalog = data.catalog;
    powerFamilies = data.families || [
      { id: "3W", name: "3W Minyatür", default_model: "OZP3S09SS05" },
      { id: "20W", name: "20W Kompakt", default_model: "OZP20S48SS05A" },
      { id: "50W", name: "50W Savunma", default_model: "OZP50S48SS05A" },
      { id: "100W", name: "100W Yüksek Güç", default_model: "OZP100S48SS05A" },
      { id: "300W", name: "300W (Yakında)", default_model: "OZP300S48SS05A" }
    ];

    // 1. Aşama: Güç Ailesi Dropdown'ını Doldur (Küçükten Büyüğe)
    if (familySelect) {
      familySelect.innerHTML = "";
      powerFamilies.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f.id;
        opt.innerText = f.id + (f.status === "COMING_SOON" || f.id === "300W" ? " (Yakında)" : "");
        opt.className = "bg-slate-900";
        familySelect.appendChild(opt);
      });
    }

    // Aktif DUT ve Güç Ailesini belirle
    const activeKey = data.active_key || "OZP50S48SS05A";
    currentDUT = fullCatalog[activeKey] || Object.values(fullCatalog)[0];
    const initialFamily = currentDUT.family || "50W";

    if (familySelect) familySelect.value = initialFamily;
    populateModelVariants(initialFamily, activeKey);

    updateDUTBadges(currentDUT);
    updateVinPresetButtons(currentDUT);
    updateCurrentLimitsForDUT(currentDUT);
  } catch (err) {
    console.warn("DUT katalog hatası:", err);
  }
}

function populateModelVariants(familyId, selectModelKey = null) {
  if (!dutSelect) return;
  dutSelect.innerHTML = "";
  
  const models = Object.values(fullCatalog).filter(m => m.family === familyId);
  models.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.model;
    opt.innerText = `${p.model} (${p.vout} / ${p.imax} | ${p.typ_eff_str})`;
    opt.className = "bg-slate-900";
    dutSelect.appendChild(opt);
  });

  if (selectModelKey && models.some(m => m.model === selectModelKey)) {
    dutSelect.value = selectModelKey;
  } else if (models.length > 0) {
    dutSelect.value = models[0].model;
  }
}

async function onFamilyChange() {
  if (!familySelect) return;
  const familyId = familySelect.value;
  populateModelVariants(familyId);
  await onDUTChange();
}

async function onDUTChange() {
  if (!dutSelect) return;
  const key = dutSelect.value;
  try {
    const res = await fetch("/api/dut/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_key: key })
    });
    const data = await res.json();
    if (data.dut) {
      currentDUT = data.dut;
      updateDUTBadges(currentDUT);
      updateVinPresetButtons(currentDUT);
      updateCurrentLimitsForDUT(currentDUT);
      if (sweepChartInstance) {
        sweepChartInstance.setTargetEff(currentDUT.typ_eff, currentDUT.model);
      }
    }
  } catch (err) {
    console.warn("DUT seçim hatası:", err);
  }
}

function selectCatalogDUT(modelKey, familyId) {
  if (familySelect && familyId) {
    familySelect.value = familyId;
    populateModelVariants(familyId, modelKey);
  }
  if (dutSelect) {
    dutSelect.value = modelKey;
  }
  onDUTChange();
  switchMainTab('bench');
}

function updateCurrentLimitsForDUT(dut) {
  if (!dut) return;
  const maxI = dut.imax_val || 10.0;
  if (kioskSlider) {
    kioskSlider.max = maxI.toString();
    kioskSlider.step = maxI <= 1.0 ? "0.01" : "0.05";
    if (targetCurrent > maxI) {
      targetCurrent = maxI;
      kioskSlider.value = targetCurrent;
      if (kioskSliderVal) kioskSliderVal.innerText = targetCurrent.toFixed(3) + " A";
      sendTargetCurrent(targetCurrent);
    }
  }
}

function updateDUTBadges(dut) {
  if (!dut) return;
  const catTarget = document.getElementById("gaugeCatTarget");
  if (catTarget) catTarget.innerText = dut.typ_eff_str || "%90";
  if (dutCatalogEffBadge) dutCatalogEffBadge.innerText = dut.typ_eff_str || "%90";
  if (dutPowerBadge) dutPowerBadge.innerText = dut.power || "50W";
  if (dutVinBadge) dutVinBadge.innerText = dut.vin_range || "18-72VDC";
  if (gaugeDutLabel) gaugeDutLabel.innerText = dut.model || "OZP50S48SS05A";
  if (gaugeInstance) {
    gaugeInstance.setTargetEfficiency(dut.typ_eff);
  }
}

// 3 Ana Sekme Arasında Geçiş Yap
function switchMainTab(tabId) {
  activeMainTab = tabId;

  const viewBench = document.getElementById("tabViewBench");
  const viewSweep = document.getElementById("tabViewSweep");
  const viewCatalog = document.getElementById("tabViewCatalog");

  const btnBench = document.getElementById("navTabBench");
  const btnSweep = document.getElementById("navTabSweep");
  const btnCatalog = document.getElementById("navTabCatalog");

  // Gizle / Göster
  if (viewBench) viewBench.classList.toggle("hidden", tabId !== "bench");
  if (viewSweep) viewSweep.classList.toggle("hidden", tabId !== "sweep");
  if (viewCatalog) viewCatalog.classList.toggle("hidden", tabId !== "catalog");

  // İnce Zarif Sekme Çizgisi Stilleri
  const activeClass = "text-rose-400 font-extrabold border-b-2 border-rose-500 pb-2 px-6 text-xs font-mono tracking-widest uppercase transition-all duration-200 shadow-[0_2px_12px_rgba(225,29,72,0.35)]";
  const inactiveClass = "text-slate-400 hover:text-slate-200 border-b-2 border-transparent pb-2 px-6 text-xs font-mono tracking-widest uppercase transition-all duration-200";

  if (btnBench) btnBench.className = (tabId === "bench" ? activeClass : inactiveClass);
  if (btnSweep) btnSweep.className = (tabId === "sweep" ? activeClass : inactiveClass);
  if (btnCatalog) btnCatalog.className = (tabId === "catalog" ? activeClass : inactiveClass);

  if (tabId === "sweep" && sweepChartInstance) {
    pollSweepStatus();
    setTimeout(() => sweepChartInstance.resizeAndDraw(), 50);
  }
}

// Standard 5 / 10 / 15 / 20 W preset.
function setStandardSweepPreset() {
  const sStart = document.getElementById("sweepStart");
  const sEnd = document.getElementById("sweepEnd");
  const sStep = document.getElementById("sweepStep");
  const sDwell = document.getElementById("sweepDwell");
  if (sStart) sStart.value = "5";
  if (sEnd) sEnd.value = "20";
  if (sStep) sStep.value = "5";
  if (sDwell) sDwell.value = "5.0";
  const txt = document.getElementById("sweepProgressText");
  if (txt) txt.innerText = "5 - 20 W Tarama Hazır";
  startSweep();
}

// Power-based efficiency sweep.
let sweepIdentificationPending = false;

function updateSweepModelLabel(model, slot) {
  const label = document.getElementById("sweepDetectedModel");
  if (label) label.innerText = `Yuva ${slot} · Belirlenen modül: ${model}`;
}

async function startSweep() {
  const startPower = Number(document.getElementById("sweepStart").value);
  const endPower = Number(document.getElementById("sweepEnd").value);
  const stepPower = Number(document.getElementById("sweepStep").value);
  const dwell = parseFloat(document.getElementById("sweepDwell")?.value || 5.0);
  sweepIdentificationPending = true;
  const modelLabel = document.getElementById("sweepDetectedModel");
  if (modelLabel) modelLabel.innerText = "Modül belirleniyor...";

  switchMainTab("sweep");
  if (btnStartSweep) btnStartSweep.disabled = true;
  if (sweepStatusBadge) {
    sweepStatusBadge.innerText = "YUVA / ÇIKIŞ KONTROLÜ";
    sweepStatusBadge.className = "px-2.5 py-1 rounded-md text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-700 animate-pulse";
  }
  if (sweepProgressText) sweepProgressText.innerText = "Seçili yuva ve modül çıkışı doğrulanıyor...";

  try {
    const res = await fetch("/api/sweep/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start_power_w: startPower,
        end_power_w: endPower,
        step_power_w: stepPower,
        dwell_time_sec: dwell,
        slot: Number.parseInt(document.getElementById("sweepSlot").value, 10),
        rated_power_w: Number(document.getElementById("sweepPower").value)
      })
    });
    const data = await res.json();
    console.log("[Sweep] 10 Noktalı Tarama Başlatıldı:", data);

    if (!res.ok || data.status !== "started") {
      if (modelLabel) modelLabel.innerText = "Modül belirlenemedi; tarama başlatılmadı.";
      onSweepFinished(data.message || "Verimlilik taraması başlatılamadı.");
      return;
    }
    if (data.config?.end_power_w < endPower) {
      const endInput = document.getElementById("sweepEnd");
      if (endInput) endInput.value = data.config.end_power_w;
    }

    if (btnStartSweep) btnStartSweep.classList.add("hidden");
    if (btnStopSweep) btnStopSweep.classList.remove("hidden");
    if (sweepStatusBadge) {
      sweepStatusBadge.innerText = "TARANIYOR (STABİLİZE)...";
      sweepStatusBadge.className = "px-2.5 py-1 rounded-md text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-700 animate-pulse";
    }

    if (data.detected_model) {
      updateSweepModelLabel(data.detected_model.model, data.config.slot);
      currentDUT = data.detected_model;
      updateDUTBadges(currentDUT);
      if (familySelect) familySelect.value = currentDUT.family;
      populateModelVariants(currentDUT.family);
      if (dutSelect) dutSelect.value = data.model_key;
    }
    if (sweepChartInstance) {
      sweepChartInstance.clear();
      if (data.detected_model) sweepChartInstance.setTargetEff(data.detected_model.typ_eff, data.dut);
    }

    clearInterval(sweepPollTimer);
    sweepPollTimer = setInterval(pollSweepStatus, 500);
  } catch (err) {
    console.warn("Sweep başlatma hatası:", err);
    if (modelLabel) modelLabel.innerText = "Modül belirleme veya tarama isteği başarısız.";
    onSweepFinished(err.message || "Verimlilik taraması başlatılamadı.");
  } finally {
    sweepIdentificationPending = false;
  }
}

async function stopSweep() {
  try {
    await fetch("/api/sweep/stop", { method: "POST" });
    onSweepFinished();
  } catch (err) {
    console.warn("Sweep durdurma hatası:", err);
  }
}

async function pollSweepStatus() {
  try {
    const res = await fetch("/api/sweep/status");
    const data = await res.json();

    if (sweepProgressBar) sweepProgressBar.style.width = `${data.progress}%`;
    if (sweepProgressText) {
      const pct = Math.round((data.current_target / Number(document.getElementById("sweepPower").value)) * 100);
      sweepProgressText.innerText = `Adım ${data.current_step}/${data.total_steps} (${data.current_target.toFixed(1)}W | %${pct}) - %${data.progress.toFixed(0)}`;
    }

    if (sweepChartInstance && data.points) {
      if (!sweepIdentificationPending && (data.is_running || data.points.length > 0)) {
        updateSweepModelLabel(data.dut_model, data.slot);
      }
      const testedModel = Object.values(fullCatalog).find(model => model.model === data.dut_model);
      if (testedModel) sweepChartInstance.setTargetEff(testedModel.typ_eff, testedModel.model);
      sweepChartInstance.setPoints(data.points);
    }

    // Tabloyu güncelle (% Yük ve Kararlılık sütunlarıyla)
    updateSweepTable(data.points);

    if (!data.is_running) {
      onSweepFinished(data.error || null);
    }
  } catch (err) {
    console.warn("Sweep sorgu hatası:", err);
  }
}

function updateSweepTable(points) {
  const tbody = document.getElementById("sweepTableBody");
  if (!tbody || !points || points.length === 0) return;
  tbody.innerHTML = points.slice(-10).map(p => {
    const loadPct = p.load_pct !== undefined ? p.load_pct : Math.round((p.i_out / 4.0) * 100);
    const stab = p.stability_std !== undefined ? `±${p.stability_std.toFixed(2)}%` : "±0.05%";
    return `
    <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 font-mono text-xs">
      <td class="py-1.5 px-2 text-white font-bold">${p.step}</td>
      <td class="py-1.5 px-2 text-cyan-300 font-extrabold">%${loadPct.toFixed(0)}</td>
      <td class="py-1.5 px-2 text-cyan-300">${Number(p.p_target || 0).toFixed(1)}W</td>
      <td class="py-1.5 px-2 text-cyan-400 font-bold">${p.i_out.toFixed(3)}A</td>
      <td class="py-1.5 px-2 text-white">${p.v_out.toFixed(3)}V</td>
      <td class="py-1.5 px-2 text-amber-300">${p.p_in.toFixed(3)}W</td>
      <td class="py-1.5 px-2 text-emerald-400 font-bold">${p.p_out.toFixed(3)}W</td>
      <td class="py-1.5 px-2 font-black ${p.efficiency >= 87 ? 'text-emerald-400' : 'text-rose-400'}">${p.efficiency.toFixed(1)}%</td>
      <td class="py-1.5 px-2 text-slate-400">${p.p_loss.toFixed(3)}W</td>
      <td class="py-1.5 px-2 text-emerald-300 text-[11px] font-semibold">${stab}</td>
    </tr>
  `;
  }).join("");
}

function onSweepFinished(error = null) {
  clearInterval(sweepPollTimer);
  if (btnStartSweep) btnStartSweep.disabled = false;
  if (btnStartSweep) btnStartSweep.classList.remove("hidden");
  if (btnStopSweep) btnStopSweep.classList.add("hidden");
  if (sweepStatusBadge) {
    sweepStatusBadge.innerText = error ? "TARAMA DURDU" : "TAMAMLANDI ✓";
    sweepStatusBadge.className = error
      ? "px-2.5 py-1 rounded-md text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-700"
      : "px-2.5 py-1 rounded-md text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-700";
  }
  if (error && sweepProgressText) sweepProgressText.innerText = error;
}

// CSV Dışa Aktarma (Export)
function exportSweepCSV() {
  window.location.href = "/api/sweep/export-csv";
}

// COM Portlarını Getir
async function ensureBenchPorts() {
  try {
    const response = await fetch("/api/ports/ensure", { method: "POST" });
    const data = await response.json();
    if (data.status !== "success") console.warn("Cihaz bağlantısı eksik:", data);
  } catch (err) {
    console.warn("Cihaz portları başlatılamadı:", err);
  }
}

async function refreshPorts() {
  try {
    const res = await fetch("/api/ports");
    const data = await res.json();
    const ports = data.ports || [];
    const utlSelect = document.getElementById("utlPort");
    if (!utlSelect) return;

    utlSelect.innerHTML = "";
    if (ports.length === 0) {
      const opt = document.createElement("option");
      opt.value = "COM3";
      opt.innerText = "COM3 (UTL8511 RS232)";
      utlSelect.appendChild(opt);
    } else {
      ports.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.device;
        opt.innerText = `${p.device} (${p.description.substring(0, 15)})`;
        utlSelect.appendChild(opt);
      });
    }

    const stRes = await fetch("/api/status");
    const stData = await stRes.json();
    if (stData.load_port) {
      utlSelect.value = stData.load_port;
    }
  } catch (err) {
    console.warn("Port tarama hatası:", err);
  }
}

async function onPortChange() {
  const utlSelect = document.getElementById("utlPort");
  if (!utlSelect) return;
  try {
    await fetch("/api/ports/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hmp_port: "", utl_port: utlSelect.value })
    });
  } catch (err) {
    console.warn("Port yapılandırma hatası:", err);
  }
}

// ================= PSU & YÜK BAĞIMSIZ AÇMA / KAPAMA =================
async function loadSlotCalibration() {
  const status = document.getElementById("slotCalibrationStatus");
  const slot = Number.parseInt(document.getElementById("singleModuleSlot")?.value || "3", 10);
  try {
    const response = await fetch("/api/calibration/slots");
    const data = await response.json();
    const profile = data.profiles?.[String(slot)];
    if (!status || !profile) return;
    if (!profile.calibrated_at) {
      status.innerText = `Yuva ${slot}: henüz kalibre edilmedi (düzeltmeler 0)`;
      status.className = "text-[11px] font-mono text-amber-300";
      return;
    }
    status.innerText = `Yuva ${slot}: Rin ${(profile.input_resistance_ohm * 1000).toFixed(1)} mΩ · Rout ${(profile.output_resistance_ohm * 1000).toFixed(1)} mΩ · kalibre ${new Date(profile.calibrated_at).toLocaleString()}`;
    status.className = "text-[11px] font-mono text-emerald-300";
  } catch (err) {
    if (status) status.innerText = "Kalibrasyon profili okunamadı.";
    console.warn("Yuva kalibrasyonu okunamadı:", err);
  }
}

async function saveSlotCalibration() {
  const slot = Number.parseInt(document.getElementById("singleModuleSlot")?.value || "3", 10);
  const value = id => Number.parseFloat(document.getElementById(id)?.value);
  const references = Object.fromEntries(["A", "B"].map(point => [point, {
    vin_dut_v: value(`slotCal${point}_vin_dut`),
    vout_dut_v: value(`slotCal${point}_vout_dut`)
  }]));
  const status = document.getElementById("slotCalibrationStatus");
  if (Object.values(references).some(point => Object.values(point).some(number => !Number.isFinite(number)))) {
    if (status) {
      status.innerText = "A ve B için DUT giriş/çıkış multimetre değerlerini girin.";
      status.className = "text-[11px] font-mono text-rose-300";
    }
    return;
  }
  try {
    const response = await fetch("/api/calibration/slot/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot, references })
    });
    const data = await response.json();
    if (data.status !== "success") throw new Error(data.message || "Kalibrasyon kaydedilemedi.");
    await loadSlotCalibration();
    if (status) status.innerText += " · kayıtlı";
  } catch (err) {
    if (status) {
      status.innerText = err.message || "Kalibrasyon kaydedilemedi.";
      status.className = "text-[11px] font-mono text-rose-300";
    }
  }
}

async function captureSlotCalibrationPoint(point) {
  const slot = Number.parseInt(document.getElementById("singleModuleSlot")?.value || "3", 10);
  const current = Number.parseFloat(document.getElementById(`slotCal${point}_current`)?.value);
  const status = document.getElementById("slotCalibrationStatus");
  if (!Number.isFinite(current) || current <= 0) return;
  if (status) { status.innerText = `Yuva ${slot}: ${point} noktası uygulanıyor; çıkış açık kalacak.`; status.className = "text-[11px] font-mono text-amber-300"; }
  try {
    const response = await fetch("/api/calibration/capture", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slot, point, output_current_a: current }) });
    const data = await response.json();
    if (data.status !== "ready") throw new Error(data.message || "Ölçüm noktası alınamadı.");
    const r = data.instrument_readings;
    document.getElementById(`slotCal${point}_reading`).innerText = `PSU: ${r.vin_source_v.toFixed(3)} V, giriş: ${r.iin_a.toFixed(3)} A · Yük: ${r.vout_load_v.toFixed(3)} V, ${r.iout_a.toFixed(3)} A. Multimetreyi modül pinlerinde ölçün.`;
    if (status) status.innerText = `Yuva ${slot}: ${point} noktası hazır. Multimetre ölçümünü girin; kaynak açık.`;
  } catch (err) {
    if (status) { status.innerText = err.message || "Ölçüm noktası alınamadı."; status.className = "text-[11px] font-mono text-rose-300"; }
  }
}

async function cancelSlotCalibration() {
  const status = document.getElementById("slotCalibrationStatus");
  try {
    await fetch("/api/calibration/cancel", { method: "POST" });
    if (status) { status.innerText = "Kalibrasyon iptal edildi; PSU, yük ve röle kapatıldı."; status.className = "text-[11px] font-mono text-slate-300"; }
  } catch (err) { if (status) status.innerText = err.message || "Kapatma isteği başarısız."; }
}

async function detectModule() {
  slotTestOutcomes.clear();
  updateActiveSlotUI(latestSlotState);
  const button = document.getElementById("btnDetectModule");
  const result = document.getElementById("moduleDetectionResult");
  if (trendChartInstance) trendChartInstance.showLiveTrend();
  if (button) { button.disabled = true; button.innerText = "TEST EDİLİYOR..."; }
  if (result) { result.className = "text-[11px] font-mono text-amber-300"; result.innerText = "24 V calisma / 10 V giris araligi testi sürüyor"; }
  try {
    const response = await fetch("/api/module/detect", { method: "POST" });
    const data = await response.json();
    const slotResults = document.getElementById("moduleSlotResults");
    const moduleResults = data.results || [];
    for (const item of moduleResults) {
      const failedPerformance = (item.performance_tests || []).some(point => point.status !== "skipped" && point.passed === false);
      const incompletePerformance = (item.performance_tests || []).some(point => point.status === "skipped");
      slotTestOutcomes.set(Number(item.slot),
        item.status === "fault_or_empty" || failedPerformance ? "failed"
          : item.status === "working" && !incompletePerformance ? "working" : "uncertain");
    }
    await syncLoadStatus();
    if (slotResults && moduleResults.length) {
      slotResults.classList.remove("hidden");
      slotResults.innerText = moduleResults.map(item => {
        const candidateNames = (item.model_candidates || []).map(candidate => candidate.model).join(" / ");
        const label = item.model?.model
          || (candidateNames ? `Olası modeller: ${candidateNames}`
            : item.status === "working" ? "Çalışıyor; model eşleşmedi"
              : item.inference_status === "no_regulated_output" ? "24 V testinde regüle çıkış yok; yuva boş veya modül çalışmıyor"
              : "Sonuç doğrulanamadı");
        const inputRange = item.input_range ? ` · ${item.input_range}` : "";
        const nominal = item.nominal_input_voltage ? ` · ${item.nominal_input_voltage}V nominal` : "";
        const vout = item.measured_output_voltage !== undefined ? ` · Vout ${item.measured_output_voltage}V` : "";
        const inference = item.inference_status === "ambiguous" ? " · Tam model belirsiz; yük matrisi atlandı"
          : item.inference_status === "inconclusive" ? " · Giriş aralığı çıkarılamadı" : "";
        const tenVolt = item.tests?.["10V"];
        const twentyFourVolt = item.tests?.["24V"];
        const tenVoltStatus = !tenVolt?.input_voltage_verified ? "10 V giriş doğrulanamadı"
          : tenVolt.working ? "10 V altında çalışıyor; 9–36 V doğrulandı"
          : tenVolt.regulated_output ? "10 V çıkışı mevcut; prob akımı doğrulanamadı"
          : twentyFourVolt?.working ? "10 V altında çalışmıyor; 24 V altında çalışıyor"
          : "10 V altında çıkış doğrulanamadı; 24 V testine bakın";
        const rangeEvidence = tenVolt
          ? ` · 10V giriş Vout ${tenVolt.output_voltage}V (${tenVoltStatus})`
          : "";
        const matrix = item.performance_tests || [];
        const loadedPoints = matrix.length ? ` · Yuklu test ${matrix.filter(point => point.passed).length}/${matrix.length}` : "";
        return `Yuva ${item.slot}: ${label}${inputRange}${nominal}${vout}${rangeEvidence}${inference}${loadedPoints}`;
      }).join("\n");
    }
    if (result) {
      const working = moduleResults.filter(item => item.status === "working").length;
      result.className = `text-[11px] font-mono ${data.status === "complete" ? "text-emerald-300" : "text-rose-300"}`;
      result.innerText = data.status === "complete" ? `5 yuva test edildi; ${working} modül çalışıyor.` : (data.message || "Modül algılama başarısız.");
    }
    if (trendChartInstance && moduleResults.length) {
      const selectedSlot = Number.parseInt(document.getElementById("singleModuleSlot")?.value || "3", 10);
      const selectedResult = moduleResults.find(item => item.slot === selectedSlot);
      if (selectedResult) {
        const nominalPoints = (selectedResult.performance_tests || [])
          .filter(point => point.input_range_point === "Nominal" && point.status !== "skipped")
          .map(point => ({
            fraction: Number(point.load_percent) / 100,
            output_power: Number(point.output_power),
            output_voltage: Number(point.output_voltage),
            expected_output_voltage: Number(point.expected_output_voltage),
            target_current_a: Number(point.target_current),
            passed: Boolean(point.passed)
          }));
        const targetPower = nominalPoints.reduce((max, point) =>
          Math.max(max, point.target_current_a * (Number(point.expected_output_voltage)
            || Number(selectedResult.model?.vout_val) || point.output_voltage)), 0) || 10;
        trendChartInstance.showModuleTest({
          slot: selectedSlot,
          status: nominalPoints.length > 0 && nominalPoints.every(point => point.passed)
            ? "passed" : selectedResult.status,
          target_power_w: targetPower,
          measurements: nominalPoints,
          message: selectedResult.message || "Bu yuvada yük testi sonucu yok."
        });
      }
    }
    if (data.status === "complete") {
      const reportResponse = await fetch("/api/module/export-excel");
      if (!reportResponse.ok) throw new Error("Excel report download failed.");
      const reportBlob = await reportResponse.blob();
      const reportUrl = URL.createObjectURL(reportBlob);
      const downloadLink = document.createElement("a");
      downloadLink.href = reportUrl;
      downloadLink.download = "ozak_power_module_test_results.zip";
      downloadLink.click();
      URL.revokeObjectURL(reportUrl);
    }

  } catch (err) {
    if (result) { result.className = "text-[11px] font-mono text-rose-300"; result.innerText = "Modül algılama isteği başarısız oldu."; }
  } finally {
    if (button) { button.disabled = false; button.innerText = "START TEST"; }
  }
}
function readTestPowerRating() {
  const input = document.getElementById("testModulePower");
  const watts = Number(input?.value);
  if (![20, 50, 100, 300].includes(watts)) {
    const result = document.getElementById("moduleDetectionResult");
    if (result) {
      result.className = "text-[11px] font-mono text-rose-300";
      result.innerText = "Modül gücü 20, 50, 100 veya 300 W olmalı.";
    }
    input?.focus();
    return null;
  }
  return watts;
}

async function askPowerRatingAndDetect() {
  const watts = readTestPowerRating();
  if (watts === null) return;
  const family = powerFamilies.find(item => Number.parseInt(item.id, 10) === watts);
  const hasSupportedInputModels = Object.values(fullCatalog).some(model =>
    model.family === family?.id && [24, 48].includes(Number(model.vin_nom))
  );
  if (!family || !hasSupportedInputModels) {
    const result = document.getElementById("moduleDetectionResult");
    if (result) {
      result.className = "text-[11px] font-mono text-rose-300";
      result.innerText = "Lütfen desteklenen modül gücünü girin: 20, 50, 100 veya 300 W.";
    }
    return;
  }
  if (familySelect) familySelect.value = family.id;
  await onFamilyChange();
  await detectModule();
}

async function askPowerRatingAndTestSelectedSlot() {
  const slot = Number.parseInt(document.getElementById("singleModuleSlot")?.value || "2", 10);
  const watts = readTestPowerRating();
  if (watts === null) return;
  slotTestOutcomes.delete(slot);
  updateActiveSlotUI(latestSlotState);

  const button = document.getElementById("btnTestSingleModule");
  const result = document.getElementById("moduleDetectionResult");
  const slotResults = document.getElementById("moduleSlotResults");
  if (trendChartInstance) trendChartInstance.showLiveTrend();
  if (button) { button.disabled = true; button.innerText = "TEST EDİLİYOR..."; }
  if (result) {
    result.className = "text-[11px] font-mono text-amber-300";
    result.innerText = `Yuva ${slot}: min/nom/max giriş · yüksüz / tam yük testi sürüyor`;
  }
  try {
    const response = await fetch("/api/module/test-slot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot, rated_power_w: watts })
    });
    const data = await response.json();
    slotTestOutcomes.set(slot, data.status === "passed" ? "working" : data.status === "failed" ? "failed" : "uncertain");
    await syncLoadStatus();
    if (trendChartInstance) trendChartInstance.showModuleTest({ ...data, slot });
    const last = data.hold || (data.measurements || []).at(-1);
    const noLoad = data.no_load;
    if (slotResults) {
      slotResults.classList.remove("hidden");
      slotResults.innerText = `Yuva ${slot}: ${noLoad ? `boşta ${noLoad.output_voltage} V` : "boşta ölçüm yok"}`
        + (last ? ` · yüklü ${last.output_voltage} V / ${last.output_power} W` : "")
        + (data.message ? ` · ${data.message}` : "");
    }
    if (result) {
      result.className = `text-[11px] font-mono ${data.status === "passed" ? "text-emerald-300" : "text-rose-300"}`;
      result.innerText = data.status === "passed"
        ? `Yuva ${slot}: yüksüz / tam yük testi geçti`
        : (data.message || `Yuva ${slot}: test tamamlanamadı`);
    }
  } catch (err) {
    if (trendChartInstance) {
      trendChartInstance.showModuleTest({ slot, status: "error", message: "Test sonucu alınamadı.", measurements: [] });
    }
    if (result) {
      result.className = "text-[11px] font-mono text-rose-300";
      result.innerText = `Yuva ${slot}: web testi başarısız oldu`;
    }
  } finally {
    if (button) { button.disabled = false; button.innerText = "TEST YUVA"; }
  }
}

function showPowerControlError(message) {
  const result = document.getElementById("moduleDetectionResult");
  if (result) {
    result.className = "text-[11px] font-mono text-rose-300";
    result.innerText = message;
  }
}

async function togglePsuState() {
  if (btnPsuToggle.disabled) return;
  btnPsuToggle.disabled = true;
  try {
    const res = await fetch("/api/psu/state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: !isPsuActive,
        slot: Number.parseInt(document.getElementById("singleModuleSlot").value, 10)
      })
    });
    const data = await res.json();
    if (!res.ok || data.status !== "success") throw new Error(data.message || "PSU komutu ba?ar?s?z.");
    isPsuActive = Boolean(data.psu_enabled);
    updatePsuButtonUI();
    await syncLoadStatus();
  } catch (err) {
    showPowerControlError(err.message);
    await syncLoadStatus();
  } finally {
    btnPsuToggle.disabled = false;
  }
}

function updatePsuButtonUI() {
  if (!btnPsuToggle) return;
  if (isPsuActive) {
    btnPsuToggle.className = "px-3.5 py-2 rounded-xl font-mono font-black text-xs tracking-wider uppercase transition-all duration-200 bg-amber-600 hover:bg-amber-500 text-white shadow-[0_0_15px_rgba(245,158,11,0.4)] border border-amber-400/50 flex items-center gap-2 cursor-pointer";
    if (psuToggleDot) psuToggleDot.className = "w-2 h-2 rounded-full bg-white animate-pulse";
    if (psuToggleText) psuToggleText.innerText = "⚡ GİRİŞ: AÇIK";
  } else {
    btnPsuToggle.className = "px-3.5 py-2 rounded-xl font-mono font-black text-xs tracking-wider uppercase transition-all duration-200 bg-slate-800 hover:bg-slate-700 text-slate-300 shadow-sm border border-slate-700 flex items-center gap-2 cursor-pointer";
    if (psuToggleDot) psuToggleDot.className = "w-2 h-2 rounded-full bg-slate-500";
    if (psuToggleText) psuToggleText.innerText = "○ GİRİŞ: KAPALI";
  }
}

async function toggleLoadState() {
  if (btnLoadToggle.disabled) return;
  btnLoadToggle.disabled = true;
  try {
    const res = await fetch("/api/load/state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !isLoadActive })
    });
    const data = await res.json();
    if (!res.ok || data.status !== "success") throw new Error(data.message || "Y?k komutu ba?ar?s?z.");
    isLoadActive = Boolean(data.load_enabled);
    updateLoadButtonUI();
  } catch (err) {
    showPowerControlError(err.message);
    await syncLoadStatus();
  } finally {
    btnLoadToggle.disabled = false;
  }
}

function updateLoadButtonUI() {
  if (!btnLoadToggle) return;
  if (isLoadActive) {
    btnLoadToggle.className = "px-3.5 py-2 rounded-xl font-mono font-black text-xs tracking-wider uppercase transition-all duration-200 bg-emerald-600 hover:bg-emerald-500 text-white shadow-[0_0_15px_rgba(16,185,129,0.4)] border border-emerald-400/50 flex items-center gap-2 cursor-pointer";
    if (loadToggleDot) loadToggleDot.className = "w-2 h-2 rounded-full bg-white animate-pulse";
    if (loadToggleText) loadToggleText.innerText = "⚡ ÇIKIŞ: AÇIK";
  } else {
    btnLoadToggle.className = "px-3.5 py-2 rounded-xl font-mono font-black text-xs tracking-wider uppercase transition-all duration-200 bg-slate-800 hover:bg-slate-700 text-slate-300 shadow-sm border border-slate-700 flex items-center gap-2 cursor-pointer";
    if (loadToggleDot) loadToggleDot.className = "w-2 h-2 rounded-full bg-slate-500";
    if (loadToggleText) loadToggleText.innerText = "○ ÇIKIŞ: KAPALI";
  }
}

async function syncLoadStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.load_enabled !== undefined) {
      updateActiveSlotUI(data);
      isLoadActive = Boolean(data.load_enabled);
      updateLoadButtonUI();
    }
    if (data.psu_enabled !== undefined) {
      isPsuActive = Boolean(data.psu_enabled);
      updatePsuButtonUI();
    }
    if (data.target_current !== undefined) {
      targetCurrent = data.target_current;
      if (kioskSlider) kioskSlider.value = targetCurrent;
      if (kioskSliderVal) kioskSliderVal.innerText = targetCurrent.toFixed(3) + " A";
    }
  } catch (e) {}
}

// Akım Sıfırlama (Tare / Zero Offset)
async function tareLoadCurrent() {
  try {
    const res = await fetch("/api/load/tare", { method: "POST" });
    const data = await res.json();
    console.log("[Tare] Akım ofseti sıfırlandı:", data);
    const btn = document.getElementById("btnTare");
    if (btn) {
      const oldText = btn.innerText;
      btn.innerText = "SIFIRLANDI ✓";
      btn.classList.add("text-emerald-400", "border-emerald-500");
      setTimeout(() => {
        btn.innerText = oldText;
        btn.classList.remove("text-emerald-400", "border-emerald-500");
      }, 1500);
    }
  } catch (err) {
    console.warn("Tare API hatası:", err);
  }
}

// ================= PROFESYONEL HASSAS AKIM AYARLAYICI =================
let sliderDebounceTimer = null;

function stepCurrent(delta) {
  const maxI = currentDUT?.imax_val || 10.0;
  targetCurrent = Math.max(0.0, Math.min(maxI, targetCurrent + delta));
  targetCurrent = Math.round(targetCurrent * 1000) / 1000;
  if (kioskSlider) kioskSlider.value = targetCurrent;
  if (kioskSliderVal) kioskSliderVal.innerText = targetCurrent.toFixed(3) + " A";
  clearTimeout(sliderDebounceTimer);
  sendTargetCurrent(targetCurrent);
}

function onSliderInput(val) {
  targetCurrent = parseFloat(val);
  targetCurrent = Math.round(targetCurrent * 1000) / 1000;
  if (kioskSliderVal) kioskSliderVal.innerText = targetCurrent.toFixed(3) + " A";
  clearTimeout(sliderDebounceTimer);
  sliderDebounceTimer = setTimeout(() => {
    sendTargetCurrent(targetCurrent);
  }, 120);
}

async function sendTargetCurrent(current) {
  try {
    await fetch("/api/load/current", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current: current })
    });
  } catch (err) {
    console.warn("Akım ayar API hatası:", err);
  }
}

// ================= AKILLI ACİL DURDURMA =================
async function emergencyStop() {
  isPsuActive = false;
  isLoadActive = false;
  targetCurrent = 0.0;
  updatePsuButtonUI();
  updateLoadButtonUI();
  if (kioskSlider) kioskSlider.value = 0.0;
  if (kioskSliderVal) kioskSliderVal.innerText = "0.000 A";

  try {
    const res = await fetch("/api/emergency-stop", { method: "POST" });
    const data = await res.json();
    console.warn("[ACİL STOP] Sistem derhal kapatıldı:", data);
  } catch (err) {
    console.error("Acil stop hatası:", err);
  }
}

// Mod Değiştirme
async function toggleSystemMode() {
  const button = document.getElementById("modeToggleBtn");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const statusResponse = await fetch("/api/status");
    if (!statusResponse.ok) throw new Error("Sistem modu okunamadı.");
    const status = await statusResponse.json();
    const newMode = status.mode === "SIMULATION" ? "HARDWARE" : "SIMULATION";
    const res = await fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: newMode })
    });
    const data = await res.json();
    if (!res.ok || data.status !== "success") throw new Error(data.message || "Mod değiştirilemedi.");
    systemMode = data.mode;
    if (modeText) modeText.innerText = data.mode === "HARDWARE" ? "TEST MODU" : "SİMÜLASYON";
    await syncLoadStatus();
  } catch (err) {
    showPowerControlError(err.message);
  } finally {
    button.disabled = false;
  }
}

// Pik Sıfırla
async function resetPeakEff() {
  try {
    await fetch("/api/reset-peak", { method: "POST" });
  } catch (err) {}
}

// ================= DİNAMİK GİRİŞ VOLTAJ PRESETLERİ (Min / Nom / Max) =================
let currentVinBand = 48.0;
let currentVinBandType = 'nom'; // 'min', 'nom', 'max'

function getVinBandValues(dut) {
  if (!dut) return { min: 18.0, nom: 48.0, max: 72.0 };
  if (dut.vin_min && dut.vin_nom && dut.vin_max) {
    return { min: dut.vin_min, nom: dut.vin_nom, max: dut.vin_max };
  }
  const range = (dut.vin_range || "").toLowerCase();
  if (range.includes("3-18") || dut.family === "3W") {
    return { min: 3.0, nom: 9.0, max: 18.0 };
  }
  if (range.includes("9-36")) {
    return { min: 9.0, nom: 24.0, max: 36.0 };
  }
  return { min: 18.0, nom: 48.0, max: 72.0 };
}

function updateVinPresetButtons(dut) {
  const bands = getVinBandValues(dut);
  const bMin = document.getElementById("vinBandMin");
  const bNom = document.getElementById("vinBandNom");
  const bMax = document.getElementById("vinBandMax");

  if (bMin) bMin.innerText = `${bands.min}V Min`;
  if (bNom) bNom.innerText = `${bands.nom}V Nom`;
  if (bMax) bMax.innerText = `${bands.max}V Max`;

  // Model değiştiğinde nominal gerilimi seç
  selectVinBand('nom');
}

async function selectVinBand(bandOrVolts) {
  const bands = getVinBandValues(currentDUT);
  let v = bands.nom;
  if (bandOrVolts === 'min') {
    v = bands.min;
    currentVinBandType = 'min';
  } else if (bandOrVolts === 'max') {
    v = bands.max;
    currentVinBandType = 'max';
  } else if (bandOrVolts === 'nom') {
    v = bands.nom;
    currentVinBandType = 'nom';
  } else {
    v = parseFloat(bandOrVolts) || bands.nom;
    if (Math.abs(v - bands.min) < 0.1) currentVinBandType = 'min';
    else if (Math.abs(v - bands.max) < 0.1) currentVinBandType = 'max';
    else currentVinBandType = 'nom';
  }

  currentVinBand = v;

  const bMin = document.getElementById("vinBandMin");
  const bNom = document.getElementById("vinBandNom");
  const bMax = document.getElementById("vinBandMax");

  const activeCls = "px-2.5 py-1 rounded cursor-pointer text-amber-300 font-bold bg-amber-500/20 shadow-sm border border-amber-500/40 transition";
  const inactiveCls = "px-2.5 py-1 rounded cursor-pointer text-slate-400 hover:text-white transition";

  if (bMin) bMin.className = (currentVinBandType === 'min') ? activeCls : inactiveCls;
  if (bNom) bNom.className = (currentVinBandType === 'nom') ? activeCls : inactiveCls;
  if (bMax) bMax.className = (currentVinBandType === 'max') ? activeCls : inactiveCls;

  const psuCalibText = document.getElementById("psuCalibText");
  const kioskVinTop = document.getElementById("kioskVinTop");
  const kioskIinTop = document.getElementById("kioskIinTop");
  const kioskPin = document.getElementById("kioskPin");

  let text = `&bull; ${v.toFixed(3)}V UDP6731 (Canlı 4-Wire Sense & SCPI)`;
  if (psuCalibText) psuCalibText.innerHTML = text;
  if (kioskVinTop) kioskVinTop.innerText = v.toFixed(3) + " V";

  const currentPout = parseFloat(document.getElementById("kioskPout")?.innerText || "0.000");
  if (currentPout > 0.1 && kioskIinTop && kioskPin) {
    const estPin = currentPout / 0.885;
    const estIin = estPin / v;
    kioskPin.innerText = estPin.toFixed(3);
    kioskIinTop.innerText = estIin.toFixed(3) + " A";
  }

  try {
    const res = await fetch("/api/psu/voltage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voltage: v })
    });
    const resData = await res.json();
    console.log("[PSU] Voltaj seçildi:", resData);
  } catch (err) {
    console.warn("Gerilim seçim hatası:", err);
  }
}
window.selectVinBand = selectVinBand;

// Tam Ekran F11
function toggleFullScreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    }
  }
}

// Global Pencere Fonksiyonları
window.startSweep = startSweep;
window.setStandardSweepPreset = setStandardSweepPreset;
window.stopSweep = stopSweep;
window.switchMainTab = switchMainTab;
window.stepCurrent = stepCurrent;
window.togglePsuState = togglePsuState;
window.detectModule = detectModule;
window.askPowerRatingAndDetect = askPowerRatingAndDetect;
window.toggleLoadState = toggleLoadState;
window.tareLoadCurrent = tareLoadCurrent;
window.emergencyStop = emergencyStop;
window.toggleSystemMode = toggleSystemMode;
window.selectCatalogDUT = selectCatalogDUT;
window.onFamilyChange = onFamilyChange;
window.onDUTChange = onDUTChange;
window.exportSweepCSV = exportSweepCSV;
window.toggleFullScreen = toggleFullScreen;
window.onSliderInput = onSliderInput;
window.loadSlotCalibration = loadSlotCalibration;
window.saveSlotCalibration = saveSlotCalibration;
window.captureSlotCalibrationPoint = captureSlotCalibrationPoint;
window.cancelSlotCalibration = cancelSlotCalibration;

window.addEventListener("DOMContentLoaded", async () => {
  if (typeof EfficiencyGauge !== "undefined") {
    gaugeInstance = new EfficiencyGauge("kioskGaugeArc", "kioskEffVal", "kioskPeakEff", "kioskGaugeDelta", "kioskOuterTrack");
  }
  if (typeof TelemetryTrendChart !== "undefined") {
    trendChartInstance = new TelemetryTrendChart("kioskCanvas", 60);
  }
  if (typeof SweepCurveChart !== "undefined") {
    sweepChartInstance = new SweepCurveChart("sweepCanvas");
  }

  // Doğrudan Buton Tıklama Dinleyicileri
  const bMin = document.getElementById("vinBandMin");
  const bNom = document.getElementById("vinBandNom");
  const bMax = document.getElementById("vinBandMax");
  if (bMin) bMin.addEventListener("click", () => selectVinBand('min'));
  if (bNom) bNom.addEventListener("click", () => selectVinBand('nom'));
  if (bMax) bMax.addEventListener("click", () => selectVinBand('max'));

  await ensureBenchPorts();
  loadSlotCalibration();
  loadDUTCatalog();
  syncLoadStatus();
  refreshPorts();
  initWebSocket();
  pollSweepStatus();
});
