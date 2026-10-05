@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo ============================================================
echo   PIPELINE DE TRANSCRICAO E RESUMO (sem portal)
echo ============================================================
echo.
echo Coloque os videos/audios em dados\1_Videos antes de executar.
echo.

rem Usa o ambiente virtual criado pelo Instalar.bat, se existir.
rem Modelo e dispositivo (cuda/cpu) vem do config.json.
set PYEXE=python
if exist ".venv\Scripts\python.exe" set PYEXE=.venv\Scripts\python.exe

"%PYEXE%" "src\pipeline.py" --modo simples

set PIPELINE_ERRO=%errorlevel%

echo.
echo ============================================================

if %PIPELINE_ERRO% neq 0 (
    echo   ERRO: O PIPELINE PAROU COM FALHA ^(codigo %PIPELINE_ERRO%^)
    echo   Veja o traceback acima e o log mais recente em dados\5_Logs
) else (
    echo   PROCESSAMENTO FINALIZADO COM SUCESSO
)

echo ============================================================
echo.
pause
