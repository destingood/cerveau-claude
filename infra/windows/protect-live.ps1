<#
.SYNOPSIS
    Met config/live.yaml hors de portée du compte Windows courant (R3, niveau 3 ; ADR-003).

.DESCRIPTION
    Lancé à la main par Lucas, dans un PowerShell « Exécuter en tant qu'administrateur ».
    Claude Code ne lance jamais ce script.

    Protection (par défaut) :
      - le groupe Administrateurs devient propriétaire du fichier (le propriétaire peut toujours
        réécrire les droits ; il ne doit donc pas être le compte courant) ;
      - l'héritage est coupé ; Administrateurs et SYSTEM gardent le contrôle total ;
      - le compte courant ne garde que la lecture.
    Claude Code tourne sous ce compte sans élévation : il peut lire le fichier, pas le modifier.
    Les groupes sont désignés par SID pour fonctionner quelle que soit la langue de Windows.

    Limite connue (docs/threat-model.md) : le compte courant garde le contrôle total du dossier
    config/ ; il peut donc supprimer ou renommer le fichier, puis en recréer un. La parade prévue
    est dans le chargeur : avant d'accepter « enabled: true », il exigera que live.yaml appartienne
    aux Administrateurs (backlog, phase de l'exécution réelle).

.PARAMETER Unprotect
    Rend le fichier au compte courant et rétablit les droits hérités, avant une modification
    manuelle par Lucas. Relancer ensuite le script sans option.

.PARAMETER Check
    Affiche le propriétaire et les droits, puis tente une ouverture en écriture sans rien écrire.
    À lancer SANS élévation pour voir ce que voit Claude Code.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File infra\windows\protect-live.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File infra\windows\protect-live.ps1 -Check
#>
[CmdletBinding(DefaultParameterSetName = 'Protect')]
param(
    [Parameter(ParameterSetName = 'Unprotect', Mandatory = $true)]
    [switch]$Unprotect,

    [Parameter(ParameterSetName = 'Check', Mandatory = $true)]
    [switch]$Check,

    [string]$Path = (Join-Path $PSScriptRoot '..\..\config\live.yaml'),

    [string]$User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AdministratorsSid = '*S-1-5-32-544'
$SystemSid = '*S-1-5-18'

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe a échoué (code $LASTEXITCODE)."
    }
}

function Test-Elevated {
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$Path = (Resolve-Path -LiteralPath $Path).Path

if ($Check) {
    $acl = Get-Acl -LiteralPath $Path
    Write-Host "Fichier      : $Path"
    Write-Host "Propriétaire : $($acl.Owner)"
    Invoke-Native 'icacls.exe' @($Path)
    try {
        # Opening for write and closing at once changes neither content nor timestamps.
        $stream = [System.IO.File]::Open($Path, 'Open', 'Write', 'ReadWrite')
        $stream.Close()
        Write-Host 'ÉTAT : INSCRIPTIBLE par ce compte (non protégé ou session élevée).'
        exit 1
    }
    catch [System.UnauthorizedAccessException] {
        Write-Host 'ÉTAT : protégé, écriture refusée à ce compte.'
        exit 0
    }
}

if (-not (Test-Elevated)) {
    throw 'Ce mode exige un PowerShell lancé en tant qu''administrateur.'
}

if ($Unprotect) {
    Invoke-Native 'icacls.exe' @($Path, '/setowner', $User)
    Invoke-Native 'icacls.exe' @($Path, '/reset')
    Write-Host "Protection retirée : $User est propriétaire, droits hérités rétablis."
    Write-Host 'Après la modification manuelle, relancer ce script sans option.'
    exit 0
}

Invoke-Native 'takeown.exe' @('/F', $Path, '/A')
Invoke-Native 'icacls.exe' @(
    $Path, '/inheritance:r',
    '/grant:r', "${AdministratorsSid}:(F)", "${SystemSid}:(F)", "${User}:(R)"
)
Write-Host "Protégé : propriétaire Administrateurs, lecture seule pour $User."
Write-Host 'Vérifier depuis un PowerShell NON élevé : protect-live.ps1 -Check'
