@echo off
title PolyXRD source mode
REM ===================================================================
REM  PolyXRD source-mode launcher for manual acceptance testing.
REM  Runs src/ directly, so it is always the current code and needs no
REM  PyInstaller build.  Usage: double-click, or run run_dev.bat.
REM
REM  KEEP THIS FILE ASCII-ONLY WITH CRLF LINE ENDINGS, AND DO NOT ADD:
REM    - parentheses inside echo text or any if-line
REM    - multi-line if-blocks
REM    - setlocal / endlocal (they discard variables, so %RC% goes empty)
REM    - goto labels
REM  The first version of this script put "(see ... docs)" inside an
REM  if-block; that literal ) closed the block early, cmd.exe failed to
REM  parse the file, and the window flashed and closed. Hence the
REM  deliberately minimal, idiom-only form below.
REM ===================================================================
cd /d "%~dp0"
REM -- UTF-8 everywhere (v1.1.1): keep console output in UTF-8 so that
REM -- Chinese/Japanese never turns into mojibake on a non-CJK Windows.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%~dp0src"

echo [PolyXRD] source mode - launching...
echo [PolyXRD] python: %~dp0venv\Scripts\python.exe
echo.

"%~dp0venv\Scripts\python.exe" -m polyxrd.main

if errorlevel 1 echo.
if errorlevel 1 echo [PolyXRD] startup failed - the error is printed above.
if errorlevel 1 echo [PolyXRD] press any key to close this window.
if errorlevel 1 pause
