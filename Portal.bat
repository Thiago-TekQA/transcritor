@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Não deixa __pycache__ espalhado pela árvore do projeto.
set PYTHONDONTWRITEBYTECODE=1

rem Usa o ambiente virtual criado pelo Instalar.bat, se existir.
set PYEXE=python
if exist ".venv\Scripts\python.exe" set PYEXE=.venv\Scripts\python.exe

"%PYEXE%" "src\portal\servidor.py"

echo.
pause
