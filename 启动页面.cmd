@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "region-tree-server" /min cmd /c python -m http.server 8899 --bind 127.0.0.1 --directory out
timeout /t 2 >nul
start "" http://127.0.0.1:8899/index.html
