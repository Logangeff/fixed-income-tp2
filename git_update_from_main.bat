@echo off
setlocal

cd /d "%~dp0"

echo Fetching latest changes from origin...
git fetch origin
if errorlevel 1 goto fail

echo Updating local main from origin/main...
git pull --rebase origin main
if errorlevel 1 goto fail

echo Done.
goto end

:fail
echo Git command failed.
exit /b 1

:end
endlocal
