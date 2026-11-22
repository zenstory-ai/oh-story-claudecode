@echo off
setlocal

set "EVENT=%~1"
if /I "%EVENT%"=="session-start" goto event_ok
if /I "%EVENT%"=="pre-tool-prose-guard" goto event_ok
if /I "%EVENT%"=="pre-tool-commit-advisory" goto event_ok
if /I "%EVENT%"=="pre-compact" goto event_ok
if /I "%EVENT%"=="post-compact" goto event_ok
if /I "%EVENT%"=="stop" goto event_ok
exit /b 2

:event_ok
set "HOOK=%~dp0story_codex_hook.js"
set "CORE=%~dp0story_hook_core.js"
if not exist "%HOOK%" goto fail_open
if not exist "%CORE%" goto fail_open
for %%I in ("%~dp0..\..") do set "CODEX_PROJECT_DIR=%%~fI"

where node >nul 2>&1
if errorlevel 1 goto fail_open

node "%HOOK%" "%EVENT%"
exit /b %ERRORLEVEL%

:fail_open
if /I "%EVENT%"=="stop" echo {"continue":true}
exit /b 0
