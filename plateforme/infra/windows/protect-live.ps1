<#
.SYNOPSIS
    Met config/live.yaml et governance/approvals/ hors de portée du compte Windows courant
    (R3, niveau 3 ; ADR-003, ADR-036).

.DESCRIPTION
    Lancé à la main par l'utilisateur, dans un PowerShell « Exécuter en tant qu'administrateur ».
    Claude Code ne lance jamais ce script.

    Protection (par défaut), pour le fichier live.yaml et pour le dossier des signatures :
      - le groupe Administrateurs devient propriétaire (le propriétaire peut toujours réécrire
        les droits ; il ne doit donc pas être le compte courant) ; pour le dossier, tout ce qu'il
        contient aussi ;
      - l'héritage est coupé ; Administrateurs et SYSTEM gardent le contrôle total ;
      - le compte courant ne garde que la lecture (et le parcours du dossier).
    Claude Code tourne sous ce compte sans élévation : il peut lire, pas modifier ni signer.
    Les groupes sont désignés par SID pour fonctionner quelle que soit la langue de Windows.

    L'adaptateur live vérifie à chaque ordre que ces deux chemins appartiennent aux
    Administrateurs (core/execution/live.py, condition « acl », B1) : un fichier supprimé puis
    recréé par le compte courant lui appartient, et l'ordre est refusé.

    Pour signer une promotion : -Unprotect, déposer la signature, puis relancer sans option.

    Limite connue (docs/threat-model.md) : le compte courant garde le contrôle total des dossiers
    parents config/ et governance/ ; il peut supprimer ou renommer ces chemins. La vérification
    du propriétaire par l'adaptateur live est la parade.

.PARAMETER Unprotect
    Rend les deux chemins au compte courant et rétablit les droits hérités, avant une
    modification manuelle par l'utilisateur. Relancer ensuite le script sans option.

.PARAMETER Check
    Affiche propriétaires et droits, puis tente une ouverture de live.yaml en écriture sans rien
    écrire. À lancer SANS élévation pour voir ce que voit Claude Code.

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

    [string]$ApprovalsPath = (Join-Path $PSScriptRoot '..\..\governance\approvals'),

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

function Test-AdministratorsOwner {
    param([string]$Target)
    $owner = (Get-Acl -LiteralPath $Target).GetOwner([Security.Principal.SecurityIdentifier])
    return $owner.Value -eq $AdministratorsSid.TrimStart('*')
}

$Path = (Resolve-Path -LiteralPath $Path).Path
$ApprovalsPath = (Resolve-Path -LiteralPath $ApprovalsPath).Path

if ($Check) {
    $protected = $true
    foreach ($target in @($Path, $ApprovalsPath)) {
        $acl = Get-Acl -LiteralPath $target
        Write-Host "Chemin       : $target"
        Write-Host "Propriétaire : $($acl.Owner)"
        Invoke-Native 'icacls.exe' @($target)
        if (-not (Test-AdministratorsOwner $target)) {
            Write-Host 'ÉTAT : le propriétaire n''est pas le groupe Administrateurs.'
            $protected = $false
        }
    }
    try {
        # Opening for write and closing at once changes neither content nor timestamps.
        $stream = [System.IO.File]::Open($Path, 'Open', 'Write', 'ReadWrite')
        $stream.Close()
        Write-Host 'ÉTAT : live.yaml INSCRIPTIBLE par ce compte (non protégé ou session élevée).'
        exit 1
    }
    catch [System.UnauthorizedAccessException] {
        Write-Host 'ÉTAT : live.yaml protégé, écriture refusée à ce compte.'
    }
    if (-not $protected) {
        exit 1
    }
    exit 0
}

if (-not (Test-Elevated)) {
    throw 'Ce mode exige un PowerShell lancé en tant qu''administrateur.'
}

if ($Unprotect) {
    Invoke-Native 'icacls.exe' @($Path, '/setowner', $User)
    Invoke-Native 'icacls.exe' @($Path, '/reset')
    Invoke-Native 'icacls.exe' @($ApprovalsPath, '/setowner', $User, '/T')
    Invoke-Native 'icacls.exe' @($ApprovalsPath, '/reset', '/T')
    Write-Host "Protection retirée : $User est propriétaire, droits hérités rétablis."
    Write-Host 'Après la modification manuelle, relancer ce script sans option.'
    exit 0
}

Invoke-Native 'takeown.exe' @('/F', $Path, '/A')
Invoke-Native 'icacls.exe' @(
    $Path, '/inheritance:r',
    '/grant:r', "${AdministratorsSid}:(F)", "${SystemSid}:(F)", "${User}:(R)"
)

# The folder and everything in it: owner first, then rights the content inherits.
# icacls rather than takeown /R, whose confirmation answer depends on the language of Windows.
Invoke-Native 'icacls.exe' @($ApprovalsPath, '/setowner', $AdministratorsSid, '/T')
Invoke-Native 'icacls.exe' @(
    $ApprovalsPath, '/inheritance:r',
    '/grant:r', "${AdministratorsSid}:(OI)(CI)(F)", "${SystemSid}:(OI)(CI)(F)", "${User}:(OI)(CI)(RX)"
)
Get-ChildItem -LiteralPath $ApprovalsPath -Force | ForEach-Object {
    Invoke-Native 'icacls.exe' @($_.FullName, '/reset', '/T')
}
Write-Host "Protégé : propriétaire Administrateurs, lecture seule pour $User."
Write-Host 'Vérifier depuis un PowerShell NON élevé : protect-live.ps1 -Check'
