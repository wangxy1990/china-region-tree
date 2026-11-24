@echo off
chcp 65001 >nul
for /f "tokens=2 delims=:" %%a in ('netstat -ano ^| findstr ":8899.*LISTENING" ^| findstr /r "TCP"') do taskkill /f /pid %%a >nul 2>&1
echo stopped
