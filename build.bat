@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
pyinstaller --clean --noconfirm skyrim_save_lab.spec

echo.
echo Build complete. Single EXE output should be here:
echo %CD%\dist\SkyrimSaveLab.exe
pause
