@echo off
rem BackupApp generated script (plan: {{PLAN}})
rem Backup + restore in one script. Usage:
rem   script.bat                  interactive (choose action)
rem   script.bat backup [-y]
rem   script.bat restore [snapshot] [-y] [--no-prebak]
rem     Restore backs up current config/data first by default;
rem     --no-prebak skips it. Omit snapshot to list backups.
rem     Retention honors count/days + monthly/yearly via PowerShell.
setlocal EnableExtensions EnableDelayedExpansion
set "APP={{APP}}"
set "DEST={{DEST}}"
set "FMT={{FMT}}"
set "COMPRESS={{COMPRESS}}"
set "KEEP={{KEEP}}"
set "MONTHLY={{MONTHLY}}"
set "YEARLY={{YEARLY}}"
set "UNIT={{RETENTION_UNIT}}"
set "SRC={{SRC}}"

set "ACTION=%~1"
set "SNAP=%~2"
set "ASSUME=0"
set "PREBAK=1"
for %%A in (%*) do (
    if /i "%%A"=="-y" set "ASSUME=1"
    if /i "%%A"=="--no-prebak" set "PREBAK=0"
)

:main
if not defined ACTION (
    choice /c BR /m "Choose action B=backup R=restore"
    if errorlevel 2 (set "ACTION=restore") else (set "ACTION=backup")
)
if /i "%ACTION%"=="backup" goto :do_backup
if /i "%ACTION%"=="restore" goto :do_restore
echo unknown action: %ACTION%
exit /b 1

:do_backup
if "%ASSUME%"=="0" (
    choice /c YN /m "Start backup? Y=yes N=no"
    if errorlevel 2 exit /b 0
)
call :backup
exit /b 0

:do_restore
if "%PREBAK%"=="1" (
    if "%ASSUME%"=="0" (
        choice /c YN /m "Backup current config/data before restore? Y=yes N=no"
        if errorlevel 2 set "PREBAK=0"
    )
)
if "%PREBAK%"=="1" call :backup
call :pick
exit /b 0

:backup
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set "TS=%%I"
if not exist "%DEST%" mkdir "%DEST%"
if "%COMPRESS%"=="1" (
    tar -a -c -f "%DEST%\%APP%_%TS%.%FMT%" {{ARCHIVE_ARGS}}
) else (
    mkdir "%DEST%\%APP%_%TS%"
{{COPY_BLOCK}}
)
if errorlevel 8 exit /b 1
if "%KEEP%" GTR 0 call :prune
echo backup done: %DEST%\%APP%_%TS%
goto :eof

:prune
rem 保留策略统一委托 PowerShell 实现（份/天 + 每月/每年第一份）
powershell -NoProfile -Command "& { $Dest='%DEST%'; $App='%APP%'; $Keep=[int]%KEEP%; $Unit='%UNIT%'; $Monthly='%MONTHLY%'; $Yearly='%YEARLY%'; $SeenM=@(); $SeenY=@(); $Now=Get-Date; $i=0; Get-ChildItem -Path $Dest -Filter ($App+'_*') | Sort-Object Name -Descending | ForEach-Object { $Snap=[regex]::Match($_.Name,'\d{8}_\d{6}').Value; if(-not $Snap){return}; $M=$Snap.Substring(0,6); $Y=$Snap.Substring(0,4); if($Unit -eq 'days'){ $In=((($Now-[datetime]::ParseExact($Snap,'yyyyMMdd_HHmmss',$null)).Days)-le $Keep) } else { $i++; $In=($i -le $Keep) }; if($In){$SeenM+=$M;$SeenY+=$Y;return}; if($Monthly -eq '1' -and $SeenM -notcontains $M){$SeenM+=$M;$SeenY+=$Y;return}; if($Yearly -eq '1' -and $SeenY -notcontains $Y){$SeenM+=$M;$SeenY+=$Y;return}; Remove-Item $_.FullName -Recurse -Force } }" >nul 2>nul
goto :eof

:pick
set "SEL=1"
if defined SNAP goto :pick2
echo Available backups:
set "N=0"
for /f "delims=" %%F in ('dir /b /o-d "%DEST%\%APP%_*" 2^>nul') do (
    set /a N+=1
    echo   !N!) %%F
)
if "%N%"=="0" echo no backup found in %DEST% & exit /b 1
set /p "SEL=Select number (default 1): "
if not defined SEL set "SEL=1"
:pick2
set "ENTRY="
if defined SNAP (
    for /f "delims=" %%F in ('dir /b /o-d "%DEST%\%SNAP%*" 2^>nul') do (
        if not defined ENTRY set "ENTRY=%%F"
    )
) else (
    set "N=0"
    for /f "delims=" %%F in ('dir /b /o-d "%DEST%\%APP%_*" 2^>nul') do (
        set /a N+=1
        if "!N!"=="%SEL%" set "ENTRY=%%F"
    )
)
if not defined ENTRY (
    if defined SNAP (echo backup not found: %SNAP%) else (echo invalid selection: %SEL%)
    exit /b 1
)
if exist "%SRC%" move "%SRC%" "%SRC%.%TS%.old" >nul 2>nul
mkdir "%SRC%" >nul 2>nul
if "%COMPRESS%"=="1" (
    tar -xf "%DEST%\%ENTRY%" -C "%SRC%"
) else (
    robocopy "%DEST%\%ENTRY%" "%SRC%" /E /R:2 /W:2 >nul
)
rem Unwrap single root directory (matches GUI restore behavior)
set "ONEDIR="
set "FILES=0"
for /f "delims=" %%X in ('dir /b /a "%SRC%" 2^>nul') do set /a FILES+=1
for /f "delims=" %%D in ('dir /b /a:d "%SRC%" 2^>nul') do set "ONEDIR=%%D"
if "%FILES%"=="1" if defined ONEDIR (
    robocopy "%SRC%\%ONEDIR%" "%SRC%" /E /MOVE /NFL /NDL /NJH /NJS /NC /NS >nul
)
echo restored from %ENTRY%
goto :eof
