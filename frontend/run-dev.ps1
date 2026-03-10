# Run frontend: install deps (if needed) and start dev server
Set-Location $PSScriptRoot
if (-not (Test-Path "node_modules")) {
    npm install
}
npm run dev
