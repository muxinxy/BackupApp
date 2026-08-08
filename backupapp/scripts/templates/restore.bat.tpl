@echo off
rem BackupApp generated restore script (plan: {{PLAN}})
rem Restores the newest snapshot. Existing source is renamed to <name>.<ts>.old
setlocal EnableExtensions
set "APP={{APP}}"
set "SRC={{SRC}}"
set "DEST={{DEST}}"
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set "DT=%%I"
set "TS=%DT:~0,8%_%DT:~8,6%"
if exist "%SRC%" ren "%SRC%" "%~nx0.%TS%.old" >nul 2>nul
if "{{COMPRESS}}"=="1" (
    for /f "delims=" %%F in ('dir /b /o-d "%DEST%\%APP%_*.{{FMT}}" 2^>nul') do (
        mkdir "%SRC%" >nul 2>nul
        tar -xf "%DEST%\%%F" -C "%SRC%\.."
        goto :done
    )
) else (
    for /f "delims=" %%F in ('dir /b /o-d "%DEST%\%APP%_*" /ad 2^>nul') do (
        robocopy "%DEST%\%%F" "%SRC%" /E /R:2 /W:2 >nul
        goto :done
    )
)
echo no backup found in %DEST%
exit /b 1
:done
echo restored from newest snapshot
exit /b 0
