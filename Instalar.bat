@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Não deixa __pycache__ espalhado pela árvore do projeto.
set PYTHONDONTWRITEBYTECODE=1

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python nao encontrado.
    echo Instale o Python 3.13 em https://www.python.org/downloads/
    echo e marque a opcao "Add python.exe to PATH" na instalacao.
    echo Depois execute este arquivo de novo.
    pause
    exit /b 1
)

python "ferramentas\instalar.py"

echo.
pause
