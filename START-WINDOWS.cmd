@echo off
cd /d "%~dp0"
py -3 -m dota_background %*
if errorlevel 1 pause
