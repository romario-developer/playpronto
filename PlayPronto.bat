@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo  PlayPronto
echo  1 = VS (instrumentos separados)
echo  2 = Playback (so tira a voz)
set /p OP=Escolha 1 ou 2:
set MODO=vs
if "%OP%"=="2" set MODO=playback
set /p LINK=Cole o link do YouTube (ou caminho do MP3) e aperte Enter:
set BPM=
set TOM=
set /p BPM=BPM (deixe vazio para detectar sozinho):
set /p TOM=Tom em semitons, ex: -2 ou 3 (vazio = original):
set EXTRA=
if not "%BPM%"=="" set EXTRA=%EXTRA% --bpm %BPM%
if not "%TOM%"=="" set EXTRA=%EXTRA% --tom %TOM%
".venv\Scripts\python.exe" criar_vs.py "%LINK%" --modo %MODO% %EXTRA%
echo.
pause
