@echo off
rem BackupApp generated backup script (plan: {{PLAN}})
rem 多源备份。bat 压缩无密码支持（zip 加密请用应用本体执行）。
setlocal EnableExtensions
set "APP={{APP}}"
set "DEST={{DEST}}"
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set "DT=%%I"
set "TS=%DT:~0,8%_%DT:~8,6%"
if not exist "%DEST%" mkdir "%DEST%"
if "{{COMPRESS}}"=="1" (
    tar -a -c -f "%DEST%\%APP%_%TS%.{{FMT}}" {{ARCHIVE_ARGS}}
) else (
    mkdir "%DEST%\%APP%_%TS%"
{{COPY_BLOCK}}
)
if errorlevel 8 exit /b 1
echo backup done: %DEST%\%APP%_%TS%
exit /b 0
