# Execute no PowerShell dentro da pasta que contem docker-compose.yml.
$ErrorActionPreference = 'Stop'
if (-not (Test-Path 'docker-compose.yml')) {
    throw 'Abra o terminal na pasta que contem docker-compose.yml e execute novamente.'
}
if (Test-Path '.env') {
    Write-Host 'O arquivo .env ja existe e nao sera sobrescrito.'
    exit 0
}
$senha = Read-Host 'Crie uma senha forte para o painel administrativo'
if ([string]::IsNullOrWhiteSpace($senha) -or $senha.Length -lt 12 -or $senha.Contains('#') -or $senha.Contains('`n') -or $senha.Contains('`r')) {
    throw 'Use pelo menos 12 caracteres, sem # e sem quebras de linha.'
}
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$chave = [Convert]::ToBase64String($bytes)
$conteudo = "ADMIN_PASSWORD=$senha`nSESSION_SECRET=$chave`nHTTPS_ONLY=false`nDATABASE_PATH=/app/data/agendamentos.db`n"
[System.IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), $conteudo, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'Arquivo .env criado com sucesso. Execute: docker compose up -d --build'
