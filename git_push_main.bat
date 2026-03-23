@echo off
setlocal

cd /d "%~dp0"

echo Staging changes...
git add .
if errorlevel 1 goto fail

set /p COMMIT_MSG=Commit message: 
if "%COMMIT_MSG%"=="" set COMMIT_MSG=Update project

git diff --cached --quiet
if not errorlevel 1 (
    echo No staged changes to commit.
    goto push
)

echo Creating commit...
git commit -m "%COMMIT_MSG%"
if errorlevel 1 goto fail

:push
echo Pushing to origin/main...
git push origin main
if errorlevel 1 goto fail

echo Done.
goto end

:fail
echo Git command failed.
exit /b 1

:end
endlocal
