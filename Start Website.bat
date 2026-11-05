@echo off
rem Double-click to open the Ghost Data Audit website.
cd /d "%~dp0"
python code\main.py serve
pause
