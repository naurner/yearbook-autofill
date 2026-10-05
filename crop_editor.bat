@echo off
rem Hand framing of the print samples in the browser (work\crop_editor.py). Close this window to stop.
cd /d "%~dp0"
start "" cmd /c "timeout /t 12 >nul & start http://127.0.0.1:8765"
python work\crop_editor.py
pause
