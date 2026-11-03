@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_inmin_v04_overnight.ps1" -KeepAwake %*
set "INMIN_EXIT_CODE=%ERRORLEVEL%"
echo INMIN finished with exit code %INMIN_EXIT_CODE%. See the output folder and console messages.
pause
exit /b %INMIN_EXIT_CODE%
