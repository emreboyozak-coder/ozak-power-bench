"""
DC-DC Buck/Boost Otomatik Verimlilik Eğrisi Tarama Motoru (Sweep Engine)
10 Adımlı (%10 - %100: 0.4A - 4.0A) nominal yük matrisi,
1.0sn elektriksel/termal oturma süresi ve 4'lü çoklu örnekleme (Trimmed Mean) stabilizasyon filtresi.
"""
import asyncio
import io
import csv
import logging
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

logger = logging.getLogger("SweepEngine")

class SweepConfig(BaseModel):
    start_power_w: float = 5.0
    end_power_w: float = 20.0
    step_power_w: float = 5.0
    output_voltage_v: float = 0.0
    max_load_current_a: float = 0.0
    dwell_time_sec: float = 5.0  # Oturma süresi (Saniye)
    samples_per_step: int = 4    # Çoklu örnekleme adedi (Trimmed Mean filtresi)
    slot: int = 2                # Five-slot relay selector slot
    rated_power_w: int = 20      # Operator-provided power family; voltage variant is detected.

class SweepPoint(BaseModel):
    p_target: float = 0.0
    step: int
    load_pct: float              # %10, %20, ..., %100
    timestamp: float
    i_target: float
    v_in: float
    i_in: float
    p_in: float
    v_out: float
    i_out: float
    p_out: float
    efficiency: float
    p_loss: float
    stability_std: float = 0.0   # Ölçüm kararlılık aralığı (±% Delta)

class SweepEngine:
    def __init__(self):
        self.is_running: bool = False
        self.progress: float = 0.0
        self.current_step: int = 0
        self.total_steps: int = 0
        self.current_target: float = 0.0
        self.points: List[SweepPoint] = []
        self._task: Optional[asyncio.Task] = None
        self.config: SweepConfig = SweepConfig()
        self.last_completed_time: Optional[float] = None
        self.dut_model: str = "OZP50S48SS05A"
        self.error: Optional[str] = None

    def set_dut_model(self, model_code: str):
        self.dut_model = model_code

    def get_status(self) -> Dict[str, Any]:
        # Fiziksel Kayıp Modeli Regresyon Katsayıları (P_loss = a*I^2 + b*I + c)
        loss_model = None
        if len(self.points) >= 3:
            try:
                import numpy as np
                x_arr = np.array([p.i_out for p in self.points])
                y_arr = np.array([p.p_loss for p in self.points])
                a, b, c = np.polyfit(x_arr, y_arr, 2)
                loss_model = {
                    "a": round(float(a), 5),
                    "b": round(float(b), 5),
                    "c": round(float(c), 5)
                }
            except Exception:
                pass

        return {
            "is_running": self.is_running,
            "progress": round(self.progress, 1),
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "current_target": self.current_target,
            "points_count": len(self.points),
            "points": [p.model_dump() for p in self.points],
            "error": self.error,
            "loss_model": loss_model,
            "last_completed_time": self.last_completed_time,
            "dut_model": self.dut_model,
            "slot": self.config.slot
        }

    async def start(self, manager, cfg: SweepConfig, relay_selector=None) -> bool:
        if self.is_running:
            return False
        if manager.emergency_stop_latched:
            manager.clear_emergency_stop()

        self.config = cfg
        self.points.clear()
        self.error = None
        self.is_running = True
        self.progress = 0.0
        self.current_step = 0

        # Adımları hesapla (0.4A'dan 4.0A'ya 0.4A artış = tam 10 nokta)
        targets = []
        power = cfg.start_power_w
        while power <= cfg.end_power_w + 1e-4:
            targets.append(round(power, 3))
            power += cfg.step_power_w

        self.total_steps = len(targets)
        self._task = asyncio.create_task(self._run_sweep_loop(manager, targets, cfg, relay_selector))
        logger.info("Power sweep started: %.1f W -> %.1f W (%s steps)", cfg.start_power_w, cfg.end_power_w, self.total_steps)
        return True

    def stop(self, manager = None):
        if self._task and not self._task.done():
            self._task.cancel()
        self.is_running = False
        if manager:
            manager.is_sweep_active = False
        logger.info("[SweepEngine] Tarama kullanıcı tarafından durduruldu.")

    async def _run_sweep_loop(self, manager, targets: List[float], cfg: SweepConfig, relay_selector=None):
        dwell_sec = max(5.0, cfg.dwell_time_sec)
        try:
            # Seri port çakışmasını engellemek için ana telemetri döngüsünü askıya al
            manager.is_sweep_active = True

            # 1. Termal Dengeleme & Başlangıç Auto-Tare (2.5 sn soğuma + artık mA sıfırlama)
            logger.info("[SweepEngine] Termal dengeleme (2.5sn) ve auto-tare uygulanıyor...")
            manager.reset_tare()
            manager.set_load_state(False)
            await asyncio.sleep(2.0)
            manager.tare_load()
            manager.set_load_state(True)
            await asyncio.sleep(0.5)

            max_ref_power = float(cfg.rated_power_w)

            for idx, target_power in enumerate(targets, start=1):
                if not self.is_running:
                    break

                sample = await manager.acquire_and_broadcast()
                if not self.is_running or manager.emergency_stop_latched:
                    break
                voltage = float(sample["v_out"])
                if voltage < cfg.output_voltage_v * 0.85:
                    raise RuntimeError("Output voltage sagged; stopped before increasing power.")
                target_amps = round(target_power / voltage, 3)
                if target_amps > cfg.max_load_current_a * 1.01:
                    raise RuntimeError("Power step exceeds the module current limit.")
                target_amps = min(target_amps, cfg.max_load_current_a)
                self.current_step = idx
                self.current_target = target_power
                self.progress = ((idx - 1) / len(targets)) * 100.0

                # 1. Yük akımını fiziksel donanıma ayarla
                if not manager.set_load_current(target_amps):
                    raise RuntimeError("Electronic load current command failed.")

                # 2. Elektriksel ve termal oturma süresi (1.2 sn)
                logger.debug(f"[SweepEngine] Adım {idx}: {target_amps:.2f}A ayarlandı. {dwell_sec:.1f}sn oturma...")
                await asyncio.sleep(dwell_sec)

                # 3. Dinamik Yakınsama (Convergence Check - Max 1.8sn)
                # Arka arkaya 3 okumada giriş akımı Delta_I < 3mA ve gerilim Delta_V < 15mV olana dek bekle
                history = []
                for conv_i in range(6):
                    if not self.is_running:
                        break
                    s = await asyncio.to_thread(manager.acquire_sync_sample)
                    await manager.broadcast(s["frame"])
                    history.append(s)
                    if len(history) >= 3:
                        last_3 = history[-3:]
                        delta_i = max(x["i_in"] for x in last_3) - min(x["i_in"] for x in last_3)
                        delta_v = max(x["v_in"] for x in last_3) - min(x["v_in"] for x in last_3)
                        if delta_i <= 0.003 and delta_v <= 0.015:
                            logger.debug(f"[SweepEngine] Yakınsama sağlandı (Adım {idx}): Delta_I={delta_i*1000:.1f}mA")
                            break
                    await asyncio.sleep(0.08)

                # 4. Kilitli 5'li Senkron Örnekleme (Lockstep Multi-sampling)
                samples = []
                for _ in range(5):
                    if not self.is_running:
                        break
                    s = await asyncio.to_thread(manager.acquire_sync_sample)
                    samples.append(s)
                    await manager.broadcast(s["frame"])
                    await asyncio.sleep(0.04)

                if not samples:
                    continue

                # 5. Uç Değer Ayıklama (5 örnekten min ve max çıkarılır, ortadaki 3 kararlı örneğin ortalaması alınır)
                if len(samples) >= 4:
                    sorted_by_eff = sorted(samples, key=lambda x: x["eff"])
                    trimmed = sorted_by_eff[1:-1]
                    eff_delta = sorted_by_eff[-1]["eff"] - sorted_by_eff[0]["eff"]
                else:
                    trimmed = samples
                    eff_delta = 0.0

                n = len(trimmed)
                avg_vin = sum(s["v_in"] for s in trimmed) / n
                avg_iin = sum(s["i_in"] for s in trimmed) / n
                avg_pin = sum(s["p_in"] for s in trimmed) / n
                avg_vout = sum(s["v_out"] for s in trimmed) / n
                avg_iout = sum(s["i_out"] for s in trimmed) / n
                avg_pout = sum(s["p_out"] for s in trimmed) / n

                if idx == 1 and (avg_vout < 1.0 or avg_pin <= 0.1 or avg_pout <= 0.02):
                    self.error = "No module output or measurable power was detected; the sweep stopped before increasing the load."
                    logger.warning("[SweepEngine] %s", self.error)
                    break

                if avg_pin > 0.1:
                    avg_eff = round((avg_pout / avg_pin) * 100.0, 2)
                else:
                    avg_eff = 0.0
                avg_ploss = round(max(0.0, avg_pin - avg_pout), 2)
                if avg_vout < cfg.output_voltage_v * 0.85 or avg_pin > cfg.rated_power_w * 1.5:
                    raise RuntimeError("Voltage sag or input power limit exceeded; sweep stopped.")
                load_pct = round((target_power / max_ref_power) * 100.0, 0)

                p = SweepPoint(
                    p_target=target_power,
                    step=idx,
                    load_pct=load_pct,
                    timestamp=time.time(),
                    i_target=target_amps,
                    v_in=round(avg_vin, 3),
                    i_in=round(avg_iin, 3),
                    p_in=round(avg_pin, 2),
                    v_out=round(avg_vout, 3),
                    i_out=round(avg_iout, 3),
                    p_out=round(avg_pout, 2),
                    efficiency=avg_eff,
                    p_loss=avg_ploss,
                    stability_std=round(eff_delta, 2)
                )
                self.points.append(p)
                self.progress = (idx / len(targets)) * 100.0
                logger.info(
                    f"[SweepEngine] Adım {idx}/{len(targets)}: %{load_pct:.0f} Yük ({target_amps:.1f}A) -> "
                    f"Vout={p.v_out:.3f}V, Iout={p.i_out:.3f}A, Pin={p.p_in:.2f}W, Eff=%{p.efficiency:.2f} (Delta: ±{eff_delta:.2f}%)"
                )

            self.last_completed_time = time.time()
            if self.error is None:
                self.progress = 100.0
                logger.info("[SweepEngine] 10 Noktalı Tarama başarıyla tamamlandı.")

        except asyncio.CancelledError:
            logger.warning("[SweepEngine] Tarama döngüsü iptal edildi.")
        except Exception as e:
            self.error = str(e)
            logger.error(f"[SweepEngine] Hata: {e}", exc_info=True)
        finally:
            self.is_running = False
            manager.is_sweep_active = False
            try:
                manager.set_load_state(False)
                manager.set_load_current(0.0)
                source_disabled = manager.set_psu_state(False)
            except Exception:
                source_disabled = False
            if relay_selector is not None:
                if source_disabled:
                    try:
                        await asyncio.to_thread(relay_selector.all_off)
                        await asyncio.to_thread(relay_selector.disconnect)
                        manager.set_active_slot(None)
                    except Exception:
                        pass
                else:
                    logger.error("[SweepEngine] PSU OFF was not acknowledged; relay state left unchanged.")

    def generate_csv(self, dut_catalog_eff: str = "%90") -> str:
        """Ozak Power kurumsal başlıklı test raporu CSV metni üretir."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Kurumsal Başlık
        writer.writerow(["# ========================================================="])
        writer.writerow(["# OZAK POWER - ISOLATED DC/DC CONVERTER EFFICIENCY REPORT"])
        writer.writerow(["# 'Keep limits out!' | Yerli Uretim, Yerli Tasarim, Milli Gurur!"])
        writer.writerow([f"# Tarih/Saat: {time.strftime('%Y-%m-%d %H:%M:%S')}"])
        writer.writerow([f"# Test Edilen Model (DUT): {self.dut_model}"])
        writer.writerow([f"# Katalog Nominal Verimi: {dut_catalog_eff}"])
        writer.writerow(["# Olcum Yontemi: 4-Wire Kelvin Remote Sense (Stabilize Trimmed Mean)"])
        writer.writerow([f"# Power steps: {self.config.start_power_w} W - {self.config.end_power_w} W; step {self.config.step_power_w} W"])
        writer.writerow(["# ========================================================="])
        writer.writerow([])

        # Sütun Başlıkları
        writer.writerow([
            "Adim", "% Yuk", "Zaman (sn)", "Hedef Guc (W)", "Hedef Akim (A)",
            "V_in Toplam (V)", "I_in Seri (A)", "P_in Toplam (W)",
            "V_out Kelvin (V)", "I_out Yuk (A)", "P_out Cikis (W)",
            "Verimlilik (%)", "Termal Kayip P_loss (W)", "Kararlilik Araligi (+-% Delta)"
        ])

        # Veri Satırları
        base_t = self.points[0].timestamp if self.points else time.time()
        for p in self.points:
            rel_t = round(p.timestamp - base_t, 2)
            writer.writerow([
                p.step,
                f"%{p.load_pct:.0f}",
                rel_t,
                f"{p.p_target:.2f}",
                f"{p.i_target:.2f}",
                f"{p.v_in:.3f}",
                f"{p.i_in:.3f}",
                f"{p.p_in:.2f}",
                f"{p.v_out:.3f}",
                f"{p.i_out:.3f}",
                f"{p.p_out:.2f}",
                f"{p.efficiency:.2f}",
                f"{p.p_loss:.2f}",
                f"{p.stability_std:.2f}"
            ])

        return output.getvalue()

SWEEP_ENGINE = SweepEngine()
