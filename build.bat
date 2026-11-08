@echo off
rem Builds dist\patchwork.exe (GUI) and dist\patchwork-cli.exe (console), one file each.
cd /d "%~dp0"
python -m pip install --quiet pyinstaller -r requirements.txt || goto :fail
python -m PyInstaller patchwork.spec --noconfirm --clean || goto :fail
echo.
echo Done: dist\patchwork.exe and dist\patchwork-cli.exe
echo Put your .env next to the exes if you want; data\ is created there too.
exit /b 0
:fail
echo Build failed.
exit /b 1
