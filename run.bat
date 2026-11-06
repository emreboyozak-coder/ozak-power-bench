@echo off
title OZAK POWER - Isolated DC/DC Telemetry & Efficiency Bench
echo ==========================================================
echo   OZAK POWER - ISOLATED DC/DC TELEMETRY BENCH & KIOSK
echo   "Keep limits out!" - Yerli Uretim, Yerli Tasarim, Milli Gurur!
echo ==========================================================
echo.
echo Sunucu baslatiliyor...
echo Tarayici acilacaktir: http://localhost:8000
echo.
start "" http://localhost:8000
python main.py
pause
