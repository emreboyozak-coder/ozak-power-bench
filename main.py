"""
DC-DC Buck/Boost Telemetri Kiosk Başlatıcı
"""
import uvicorn
from backend.config import CONFIG

if __name__ == "__main__":
    print("=" * 60)
    print("  DC-DC BUCK/BOOST TELEMETRY BENCH & KIOSK PANEL")
    print("=" * 60)
    print(f"  Arayüz Erişimi: http://localhost:{CONFIG.PORT}")
    print(f"  Örnekleme Hızı: {int(CONFIG.SAMPLE_INTERVAL_SEC * 1000)} ms (Canlı WebSocket)")
    print(f"  Fuar Kiosk Modu: Tarayıcıda F11 tuşuna basarak tam ekrana geçin.")
    print("=" * 60)
    uvicorn.run(
        "backend.server:app",
        host=CONFIG.HOST,
        port=CONFIG.PORT,
        log_level="info",
        reload=False
    )
