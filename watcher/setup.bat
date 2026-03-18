@echo off
echo ========================================
echo  NLG Watcher - Configuration
echo ========================================
echo.

set /p TOKEN=GitHub Token (ghp_xxx):
set /p REPO=GitHub Repo (owner/name):

echo.
echo Lancement du watcher...
echo  Token: %TOKEN:~0,10%...
echo  Repo: %REPO%
echo  Ctrl+C pour arreter
echo ========================================
echo.

set GITHUB_TOKEN=%TOKEN%
set GITHUB_REPO=%REPO%

python "%~dp0watcher.py"
pause
