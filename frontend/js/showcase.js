/**
 * Ozak Power Fuar Vitrin / Ekran Koruyucu (Attract & Showcase Mode)
 * Vitrin yalnızca kullanıcı düğmeye bastığında açılır.
 */
(function() {
  let showcaseActive = false;
  let currentSlide = 0;
  let slideInterval = null;

  const slides = [
    {
      series: "3W ULTRA MİNYATÜR SERIES",
      model: "OZP3S09SS05",
      power: "3W",
      vin: "3–18 VDC (9V Nom)",
      vout: "5V, 9V, 12V, 15V, 24V, 28V",
      eff: "Typ. %78.8",
      tag: "ULTRA DÜŞÜK GÜÇ İZOLASYONU",
      desc: "Mikrodenetleyici ve izole haberleşme kanalları (RS-485, CAN-Bus) için ultra kompakt SMD ve DIP tasarım."
    },
    {
      series: "20W ISOLATED DC-DC SERIES",
      model: "OZP20S48SS05A",
      power: "20W",
      vin: "18–72 VDC (48V Nom)",
      vout: "5V, 12V, ±12V, 15V, ±15V",
      eff: "Typ. %89",
      tag: "MİNYATÜR DUAL ÇIKIŞ",
      desc: "Simetrik çift çıkış opsiyonları, haberleşme sistemleri ve hassas analog sensör beslemeleri için ultra düşük gürültülü güç mimarisi."
    },
    {
      series: "50W ISOLATED DC-DC SERIES",
      model: "OZP50S48SS05A",
      power: "50W",
      vin: "18–72 VDC (48V Nom)",
      vout: "5 VDC / 10A Max",
      eff: "Typ. %90",
      tag: "SAVUNMA & HAVACILIK STANDARDI",
      desc: "Zorlu çevresel koşullar, düşük EMI ve yüksek galvanik izolasyon gerektiren savunma sanayii ve endüstriyel robotik sistemler için optimize edilmiştir."
    },
    {
      series: "100W ISOLATED DC-DC SERIES",
      model: "OZP100S48SS05A",
      power: "100W",
      vin: "18–72 VDC (48V Nom)",
      vout: "5 VDC / 20A Max",
      eff: "Typ. %92'ye Varan Verim",
      tag: "YÜKSEK GÜÇ YOĞUNLUĞU",
      desc: "Kompakt alüminyum gövde, 4-telli Kelvin Remote Sense regülasyonu ve geniş 4:1 giriş aralığı ile maksimum enerji dönüşümü."
    },
    {
      series: "300W HEAVY DUTY SERIES",
      model: "OZP300S48SS05A",
      power: "300W",
      vin: "18–72 VDC (48V Nom)",
      vout: "5V, 12V, 24V, 28V, 48V (60A)",
      eff: "Typ. %91 (Hedef)",
      tag: "AR-GE AŞAMASINDA / YAKINDA",
      desc: "60A'e varan yüksek çıkış akımı, tam koruma mimarisi (OVP, OCP, OTP) ve entegre termal soğutma kanalları."
    }
  ];

  function showShowcase(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    const overlay = document.getElementById("showcaseOverlay");
    if (!overlay) return;

    showcaseActive = true;
    overlay.classList.remove("hidden");
    overlay.classList.add("flex");
    currentSlide = 0;
    renderSlide(0);

    clearInterval(slideInterval);
    slideInterval = setInterval(() => {
      currentSlide = (currentSlide + 1) % slides.length;
      renderSlide(currentSlide);
    }, 4500);
  }

  function hideShowcase(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    const overlay = document.getElementById("showcaseOverlay");
    if (!overlay) return;

    showcaseActive = false;
    overlay.classList.add("hidden");
    overlay.classList.remove("flex");
    clearInterval(slideInterval);

  }

  function nextSlide(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    currentSlide = (currentSlide + 1) % slides.length;
    renderSlide(currentSlide);
  }

  function prevSlide(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    currentSlide = (currentSlide - 1 + slides.length) % slides.length;
    renderSlide(currentSlide);
  }

  function renderSlide(idx) {
    const s = slides[idx];
    const sTitle = document.getElementById("scSeriesTitle");
    const sPower = document.getElementById("scPower");
    const sVin = document.getElementById("scVin");
    const sVout = document.getElementById("scVout");
    const sEff = document.getElementById("scEff");
    const sTag = document.getElementById("scTag");
    const sDesc = document.getElementById("scDesc");
    const sDots = document.getElementById("scDots");

    if (sTitle) sTitle.innerText = s.series;
    if (sPower) sPower.innerText = s.power;
    if (sVin) sVin.innerText = s.vin;
    if (sVout) sVout.innerText = s.vout;
    if (sEff) sEff.innerText = s.eff;
    if (sTag) sTag.innerText = s.tag;
    if (sDesc) sDesc.innerText = s.desc;

    if (sDots) {
      sDots.innerHTML = slides.map((_, i) => 
        `<button onclick="window.goToShowcaseSlide(${i}, event)" class="h-2.5 rounded-full transition-all duration-300 ${i === idx ? 'bg-rose-500 w-10 shadow-[0_0_12px_rgba(225,29,72,0.6)]' : 'bg-slate-700 w-2.5 hover:bg-slate-500'}"></button>`
      ).join("");
    }
  }

  function goToShowcaseSlide(idx, e) {
    if (e && e.stopPropagation) e.stopPropagation();
    currentSlide = idx;
    renderSlide(currentSlide);
  }

  // ESC tuşuna basıldığında vitrini kapat
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && showcaseActive) {
      hideShowcase();
    }
  });

  window.manualTriggerShowcase = showShowcase;
  window.hideShowcase = hideShowcase;
  window.nextShowcaseSlide = nextSlide;
  window.prevShowcaseSlide = prevSlide;
  window.goToShowcaseSlide = goToShowcaseSlide;

})();
