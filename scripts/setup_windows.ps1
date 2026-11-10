# One-time setup on Windows (PowerShell):   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
# Creates .venv and installs everything. The chatbot engine (llama-cpp-python) is
# installed from prebuilt CPU wheels, so no C++ compiler / Visual Studio is needed.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $python = "py"; $pyArgs = @("-3") } else { $python = "python"; $pyArgs = @() }
& $python @pyArgs -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ is required'"

if (-not (Test-Path ".venv")) { & $python @pyArgs -m venv .venv }
$venvPy = ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install --prefer-binary "llama-cpp-python>=0.3.2" `
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
& $venvPy -m pip install -r requirements.txt
Write-Host ""
Write-Host "Done. Start Airglide with:  scripts\run_windows.bat" -ForegroundColor Green
