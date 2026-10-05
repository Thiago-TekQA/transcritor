@echo off
chcp 65001 >nul
cd /d "%~dp0.."

rem Organiza as pastas de trabalho (1_Videos ... 8_Resumos, _portal) em dados\.
rem Feche o portal e qualquer pipeline em execucao antes.

set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1

set PYEXE=python
if exist ".venv\Scripts\python.exe" set PYEXE=.venv\Scripts\python.exe

echo ============================================================
echo   ORGANIZAR PASTAS DE TRABALHO EM dados\
echo ============================================================
echo.

"%PYEXE%" "ferramentas\migrar_para_dados.py"

if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

echo.
choice /C SN /M "Migrar agora"

if errorlevel 2 (
    echo Nada foi alterado.
    pause
    exit /b 0
)

"%PYEXE%" "ferramentas\migrar_para_dados.py" --executar

echo.
pause
