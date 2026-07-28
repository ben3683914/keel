@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Check if portable VSCode already exists
if exist ".vscode-portable\Code.exe" (
    goto :install_extensions
)

echo.
echo === Setting up Portable VSCode ===
echo.

:: Create temp directory
if not exist ".vscode-portable" mkdir ".vscode-portable"

:: Download latest stable VSCode portable (Windows x64 zip)
echo Downloading VSCode portable...
set "VSCODE_URL=https://code.visualstudio.com/sha/download?build=stable&os=win32-x64-archive"
set "VSCODE_ZIP=%TEMP%\vscode-portable.zip"

powershell -NoProfile -Command "Invoke-WebRequest -Uri '%VSCODE_URL%' -OutFile '%VSCODE_ZIP%' -UseBasicParsing"
if errorlevel 1 (
    echo ERROR: Failed to download VSCode. Falling back to global VSCode...
    goto :fallback
)

:: Extract
echo Extracting...
powershell -NoProfile -Command "Expand-Archive -Path '%VSCODE_ZIP%' -DestinationPath '.vscode-portable' -Force"
if errorlevel 1 (
    echo ERROR: Failed to extract VSCode. Falling back to global VSCode...
    goto :fallback
)

:: Clean up zip
del "%VSCODE_ZIP%" 2>nul

:: Create data directory (makes it portable — settings stored locally)
if not exist ".vscode-portable\data" mkdir ".vscode-portable\data"

echo VSCode portable installed.
echo.

:install_extensions
:: Install recommended extensions if extensions.json exists
if not exist ".vscode\extensions.json" goto :launch

:: Check if extensions are already installed by looking for extensions dir
set "EXT_DIR=.vscode-portable\data\extensions"
if not exist "%EXT_DIR%" mkdir "%EXT_DIR%"

:: Count existing extensions (skip if we already have some)
set "EXT_COUNT=0"
for /d %%d in ("%EXT_DIR%\*") do set /a EXT_COUNT+=1
if %EXT_COUNT% gtr 0 goto :launch

echo Installing recommended extensions...
:: Use PowerShell to reliably parse JSON and install each extension
powershell -NoProfile -Command "$exts = (Get-Content '.vscode\extensions.json' | ConvertFrom-Json).recommendations; foreach ($ext in $exts) { Write-Host \"  Installing $ext...\"; & '.vscode-portable\bin\code.cmd' --install-extension $ext --force 2>$null }"
echo Extensions installed.
echo.

:launch
echo Launching workspace...
start "" ".vscode-portable\Code.exe" "%~dp0."
goto :end

:fallback
echo.
echo Portable VSCode not available. Opening with global VSCode...
start "" code "%~dp0." 2>nul || echo ERROR: Could not find VSCode. Install it or re-run this script.

:end
endlocal
