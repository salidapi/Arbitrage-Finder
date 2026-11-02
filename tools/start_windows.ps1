$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
py -3.12 -m uv sync --frozen
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
py -3.12 -m uv run arbscanner
exit $LASTEXITCODE
