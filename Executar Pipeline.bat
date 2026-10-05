@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   PIPELINE DE TRANSCRICAO E RESUMO
echo ============================================================
echo.

rem Usa o ambiente virtual criado pelo Instalar.bat, se existir.
rem Modelo e dispositivo (cuda/cpu) vem do config.json.
set PYEXE=python
if exist ".venv\Scripts\python.exe" set PYEXE=.venv\Scripts\python.exe

"%PYEXE%" "pipeline_transcricao_reestruturado.py" --modo simples

set PIPELINE_ERRO=%errorlevel%

echo.
echo ============================================================

if %PIPELINE_ERRO% neq 0 (
    echo   ERRO: O PIPELINE PAROU COM FALHA ^(codigo %PIPELINE_ERRO%^)
    echo   Veja o traceback acima e o log mais recente em 5_Logs
) else (
    echo   PROCESSAMENTO FINALIZADO COM SUCESSO
)

echo ============================================================
echo.
pause
