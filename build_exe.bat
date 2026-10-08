@echo off
rem ============================================================
rem  Build script example for Gomoku Assistant (gomoku.py + gomoku_engine.py)
rem  Steps: 1) compile engine to .pyd with Nuitka
rem         2) package single-file exe with PyInstaller
rem         3) run self-test on the packaged exe
rem         4) output exe in .\dist\
rem  Prerequisites (Windows, x64):
rem    - FULL CPython 3.12 with headers/libs (embeddable distros do NOT work).
rem      You can get a full portable copy from the "python" nuget package:
rem      https://www.nuget.org/packages/python/3.12.10
rem    - pip install nuitka pyinstaller
rem    - MinGW64: Nuitka downloads it automatically when needed
rem  NOTE: keep this file ANSI/GBK-safe (ASCII only) — cmd parses batch files
rem        using the system codepage, UTF-8 Chinese comments may corrupt parsing.
rem ============================================================

rem >>> edit these two paths to your environment <<<
set PROJ_DIR=D:\gomoku-project
set PY_DIR=C:\Python312

cd /d "%PROJ_DIR%"

echo [1/4] Nuitka compile engine...
"%PY_DIR%\python.exe" -m nuitka --module gomoku_engine.py --output-dir=build_nuitka --mingw64 --assume-yes-for-downloads
if errorlevel 1 goto :fail

echo [2/4] Package exe (only the compiled .pyd ships; source .py moved aside temporarily)...
copy /y build_nuitka\gomoku_engine.cp312-win_amd64.pyd . >nul
move gomoku_engine.py build_nuitka\gomoku_engine_src_backup.py >nul
"%PY_DIR%\python.exe" -m PyInstaller --noconsole --onefile --name gomoku-assistant --add-data "gomoku_opening_book.json;." --hidden-import json --hidden-import random gomoku.py
set RC=%ERRORLEVEL%
move build_nuitka\gomoku_engine_src_backup.py gomoku_engine.py >nul
if not "%RC%"=="0" goto :fail

echo [3/4] Self-test the packaged exe (results are written to the log folder)...
".\dist\gomoku-assistant.exe" --selftest
echo     Check Documents\gomoku logs\selftest_result.txt: it should end with 0 failures.

echo [4/4] Done. Built exe is in .\dist\ (kept for Release upload)
rmdir /s /q build 2>nul
del /q gomoku-assistant.spec 2>nul
echo BUILD OK
exit /b 0

:fail
echo BUILD FAILED
exit /b 1
