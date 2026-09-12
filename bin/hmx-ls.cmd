@echo off
setlocal

set "ROOT=%~dp0.."

if defined HMX_LSP_PYTHON (
  set "PYTHON=%HMX_LSP_PYTHON%"
  goto run
)
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
  set "PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
  goto run
)
if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
  goto run
)
where py >nul 2>nul && (
  set "PYTHON=py -3"
  goto run
)
where python >nul 2>nul && (
  set "PYTHON=python"
  goto run
)

echo hmx-ls: no Python interpreter found. Set HMX_LSP_PYTHON or install Python 3. 1>&2
exit /b 127

:run
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
%PYTHON% -m hmx_ls.cli %*
