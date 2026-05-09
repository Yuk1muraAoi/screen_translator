$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "venv\Scripts\python.exe"
$Spec = Join-Path $Root "screen_translator.spec"
$Dist = Join-Path $Root "dist"
$DistEnvFile = Join-Path $Dist ".env"
$DistEnvExample = Join-Path $Dist ".env.example"
$DistConfig = Join-Path $Dist "config.json"
$DistHistory = Join-Path $Dist "history"

Set-Location $Root

if (-not (Test-Path $Python)) {
    throw "Cannot find venv Python: $Python"
}

if (Test-Path $DistEnvFile) {
    Remove-Item -LiteralPath $DistEnvFile -Force
}
if (Test-Path $DistConfig) {
    Remove-Item -LiteralPath $DistConfig -Force
}
if (Test-Path $DistHistory) {
    Remove-Item -LiteralPath $DistHistory -Recurse -Force
}

& $Python -m PyInstaller --clean --noconfirm $Spec
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (Test-Path $DistEnvFile) {
    Remove-Item -LiteralPath $DistEnvFile -Force
}
if (Test-Path $DistConfig) {
    Remove-Item -LiteralPath $DistConfig -Force
}
if (Test-Path $DistHistory) {
    Remove-Item -LiteralPath $DistHistory -Recurse -Force
}

@"
OPENAI_API_KEY=
OPENAI_API_BASE=
MODEL_NAME=
"@ | Set-Content -LiteralPath $DistEnvExample -Encoding UTF8
Write-Host "Created dist\\.env.example template. Rename it to .env after distribution."

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $Dist\ScreenTranslator.exe"
Write-Host ""
Write-Host "Do not distribute your local .env. Users can create their own .env next to ScreenTranslator.exe."
