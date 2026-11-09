# Career Kit one-click install (Windows PowerShell)
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Does three things: create a venv (pinned to Python 3.12 when uv is available)
# -> install deps from the official PyPI -> print the MCP
# registration command using an ABSOLUTE interpreter path (avoids the classic
# "bare `python` points at the wrong interpreter" trap).
$ErrorActionPreference = "Stop"
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$Index = "https://pypi.org/simple"

Write-Host ""
Write-Host "== Career Kit install =="
Write-Host "repo: $Root"
Write-Host ""

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Write-Host "[1/4] uv: install Python 3.12 and create venv ..."
    uv python install 3.12
    uv venv .venv --python 3.12 --clear
    Write-Host "[2/4] installing dependencies (-e .) ..."
    uv pip install -e . --index-url $Index
} else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Host "Neither python nor uv found. Install uv (recommended): https://docs.astral.sh/uv/" -ForegroundColor Red
        exit 1
    }
    Write-Host "[1/4] python -m venv .venv ..."
    & python -m venv .venv
    & $VenvPy -m pip install --upgrade pip
    Write-Host "[2/4] installing dependencies (-e .) ..."
    & $VenvPy -m pip install -e . --index-url $Index
}

if (-not (Test-Path $VenvPy)) {
    Write-Host "Install failed: interpreter not found at $VenvPy" -ForegroundColor Red
    exit 1
}

Write-Host "[3/4] dependencies done." -ForegroundColor Green

# Desktop shortcut: start the local console and open the browser (data stays local).
Write-Host "[4/4] creating desktop shortcut ..."
$Desktop = [Environment]::GetFolderPath("Desktop")
if ($Desktop -and (Test-Path $Desktop)) {
    try {
        $LinkPath = Join-Path $Desktop "Career Kit.lnk"
        $Shell = New-Object -ComObject WScript.Shell
        $Shortcut = $Shell.CreateShortcut($LinkPath)
        $Shortcut.TargetPath = $VenvPy
        $Shortcut.Arguments = "-m src.web --open"
        $Shortcut.WorkingDirectory = $Root
        $Shortcut.Description = "Career Kit local console"
        $Shortcut.Save()
        Write-Host "  desktop: $LinkPath" -ForegroundColor Green
    } catch {
        Write-Host "  shortcut skipped: $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  desktop folder not found; shortcut skipped" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Local console (also available as the desktop shortcut):"
Write-Host "  $VenvPy -m src.web --open" -ForegroundColor Yellow
Write-Host ""
Write-Host "Interpreter (use this ABSOLUTE path to register the MCP server):"
Write-Host "  $VenvPy" -ForegroundColor Yellow
Write-Host ""
Write-Host "Register with your AI agent (pick one; run from any directory):"
Write-Host ('  Claude Code :  claude mcp add career-kit -- "' + $VenvPy + '" -m src.server')
Write-Host ('  Codex CLI   :  codex mcp add career-kit -- "' + $VenvPy + '" -m src.server')
$jsonPath = $VenvPy.Replace('\', '/')
$regJson = '{"mcp":{"career-kit":{"type":"local","command":["' + $jsonPath + '","-m","src.server"],"enabled":true}}}'
Write-Host "  opencode    :  project opencode.json or global ~/.config/opencode/opencode.jsonc:"
Write-Host "    $regJson"
Write-Host ""
Write-Host "Scrapers need a browser engine (first time, optional):"
Write-Host "  $VenvPy -m playwright install chromium"
Write-Host ""
Write-Host "== Doctor =="
& $VenvPy -m src.doctor
Write-Host ""
Write-Host "Verify: start a new session and type /career-kit; a welcome guide means success."
