<#
.SYNOPSIS
    Installe les deux tâches planifiées de CERVEAU : rapport hebdomadaire et rapport de sécurité
    mensuel (§17 phase 7, ADR-066).

.DESCRIPTION
    Lancé à la main par l'utilisateur, dans un PowerShell ordinaire (sans élévation) : les tâches
    tournent sous son compte, seulement quand il est connecté, sans mot de passe enregistré.
    Claude Code ne lance jamais ce script.

    - « CERVEAU rapport hebdomadaire » : chaque lundi à 07:00, `cerveau eval` (hors ligne, ni clé
      ni appel payant) puis `cerveau report weekly`, qui couvre la dernière semaine ISO complète.
    - « CERVEAU rapport sécurité » : chaque lundi à 07:30, `cerveau report security` seulement si
      le rapport du mois (docs/rapports/securite-AAAA-MM.md) n'existe pas encore ; il tourne donc
      une fois par mois. Le module ScheduledTasks n'a pas de déclencheur mensuel.

    StartWhenAvailable rattrape une exécution manquée (PC éteint) au prochain démarrage : la
    semaine couverte reste la même, le rapport rattrapé est identique. Un rapport en échec sort
    avec le code 1 (visible dans l'historique de la tâche) et envoie l'alerte
    « rapport_planifie_en_echec » sur les canaux configurés.

    La phase 7 se clôt après quatre semaines consécutives sans échec : `uv run cerveau report
    streak`.

.PARAMETER Remove
    Supprime les deux tâches.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File infra\windows\install-schedule.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File infra\windows\install-schedule.ps1 -Remove
#>
[CmdletBinding()]
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Weekly = 'CERVEAU rapport hebdomadaire'
$Security = 'CERVEAU rapport sécurité'

if ($Remove) {
    foreach ($name in @($Weekly, $Security)) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Host 'Tâches supprimées.'
    return
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv introuvable dans le PATH : installer uv avant de planifier les rapports.'
}

function New-CerveauAction([string]$Script) {
    $quoted = $Root.Replace("'", "''")  # a quote in the path must not end the literal
    $command = "Set-Location -LiteralPath '$quoted'; $Script; exit `$LASTEXITCODE"
    New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $Root `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$command`""
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

$weeklyAction = New-CerveauAction 'uv run --frozen cerveau eval; uv run --frozen cerveau report weekly'
$securityAction = New-CerveauAction (
    "if (Test-Path ('docs\rapports\securite-' + (Get-Date -Format 'yyyy-MM') + '.md')) " +
    "{ exit 0 }; uv run --frozen cerveau report security"
)

Register-ScheduledTask -TaskName $Weekly -Force -Action $weeklyAction -Settings $settings `
    -Principal $principal -Description 'CERVEAU : évals hors ligne et rapport hebdomadaire (ADR-066)' `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '07:00') | Out-Null
Register-ScheduledTask -TaskName $Security -Force -Action $securityAction -Settings $settings `
    -Principal $principal -Description 'CERVEAU : rapport de sécurité mensuel (ADR-066)' `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '07:30') | Out-Null

Get-ScheduledTask -TaskName $Weekly, $Security |
    Select-Object TaskName, State, @{ n = 'Prochaine exécution'; e = {
        (Get-ScheduledTaskInfo -TaskName $_.TaskName).NextRunTime } } |
    Format-Table -AutoSize
