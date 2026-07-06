# Ajoute le serveur MCP "pim" à claude_desktop_config.json
# À lancer APPLI CLAUDE DESKTOP COMPLETEMENT FERMEE.

$configPath = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"

if (-not (Test-Path $configPath)) {
    Write-Error "Config introuvable : $configPath"
    exit 1
}

# Sauvegarde
Copy-Item $configPath "$configPath.bak" -Force
Write-Host "Sauvegarde -> $configPath.bak"

$config = Get-Content $configPath -Raw | ConvertFrom-Json

$pim = [ordered]@{
    command = "C:\Users\tomil\Documents\Generative-AI-M2-Apprentissage-2026-students\genai_env\Scripts\python.exe"
    args    = @("C:\Users\tomil\Documents\Generative-AI-M2-Apprentissage-2026-students\notebooks\TD4_mcp\mini_project\pim_server.py")
}

$mcpServers = [ordered]@{ pim = $pim }

$config | Add-Member -NotePropertyName mcpServers -NotePropertyValue $mcpServers -Force

$config | ConvertTo-Json -Depth 20 | Set-Content $configPath -Encoding UTF8

Write-Host "OK : serveur 'pim' ajoute. Tu peux relancer Claude Desktop."
