@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---- find python ----
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  echo [X] Python not found. Install Python 3.8+ or edit this file and set PY manually.
  pause
  exit /b 1
)

:menu
cls
echo ============================================
echo   MIUI Steps Tool  (needs root + adb)
echo ============================================
echo   1. status        - today's steps / free gaps
echo   2. set target    - set today's total (blank = random)
echo   3. add steps     - add N on top of current
echo   4. lock          - keep total fixed, trim real steps
echo   5. sync          - flush now + faster refresh
echo   6. rollback last - restore newest backup
echo   7. list backups  - with timestamps
echo   8. rollback #    - pick a backup by index
echo   9. default delay - back to 300s
echo   d. devices       - list connected devices
echo   0. exit
echo ============================================
set "c="
set /p "c=Choose: "

if "%c%"=="1" %PY% StepLocal.py status & pause & goto menu
if "%c%"=="2" goto setstep
if "%c%"=="3" goto addstep
if "%c%"=="4" goto lockstep
if "%c%"=="5" %PY% StepLocal.py sync & pause & goto menu
if "%c%"=="6" %PY% StepLocal.py rollback & pause & goto menu
if "%c%"=="7" %PY% StepLocal.py backups & pause & goto menu
if "%c%"=="8" goto rollback
if "%c%"=="9" %PY% StepLocal.py restore-delay & pause & goto menu
if /i "%c%"=="d" %PY% StepLocal.py devices & pause & goto menu
if "%c%"=="0" exit /b
goto menu

:setstep
set "n="
set /p "n=Target steps (blank = random 16000-22000, max 30000): "
if "%n%"=="" goto setrandom
%PY% StepLocal.py set %n% --live
pause
goto menu

:setrandom
%PY% StepLocal.py set --live
pause
goto menu

:addstep
set "n="
set /p "n=Steps to add: "
%PY% StepLocal.py add %n%
pause
goto menu

:lockstep
set "n="
set /p "n=Lock total at: "
%PY% StepLocal.py lock %n%
pause
goto menu

:rollback
%PY% StepLocal.py backups
set "i="
set /p "i=Rollback to index (blank = newest): "
if "%i%"=="" goto rblatest
%PY% StepLocal.py rollback %i%
pause
goto menu

:rblatest
%PY% StepLocal.py rollback
pause
goto menu
