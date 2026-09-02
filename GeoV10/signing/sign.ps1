# Signs one or more exes with the Geo code-signing certificate.
# The .pfx (private key) is NOT in the repo - keep it somewhere safe and pass it in.
#
#   powershell -File sign.ps1 -Pfx C:\keys\geo-codesign.pfx -Password 'xxx' -Files ..\..\dist\app.exe
#
# Self-signed cert: this makes the exe carry a stable publisher identity and be
# trusted on any machine that has geo-codesign.cer installed (see README.md). It
# does NOT give Microsoft SmartScreen reputation - only an OV/EV cert from a CA does.

param(
    [Parameter(Mandatory = $true)][string]$Pfx,
    [Parameter(Mandatory = $true)][string]$Password,
    [Parameter(Mandatory = $true)][string[]]$Files
)

$ErrorActionPreference = 'Stop'
# X509Certificate2 constructor works in Windows PowerShell 5.1;
# Get-PfxCertificate -Password is PowerShell 7+ only.
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($Pfx, $Password, 'Exportable,PersistKeySet')

$timestamps = @('http://timestamp.digicert.com', 'http://timestamp.sectigo.com')

foreach ($f in $Files) {
    if (-not (Test-Path $f)) { Write-Warning "missing: $f"; continue }
    $done = $false
    foreach ($t in $timestamps) {
        try {
            $r = Set-AuthenticodeSignature -FilePath $f -Certificate $cert -HashAlgorithm SHA256 -TimestampServer $t -ErrorAction Stop
            if ($r.Status -eq 'Valid' -or $r.SignerCertificate) { Write-Output "signed $f (timestamp $t)"; $done = $true; break }
        } catch { }
    }
    if (-not $done) {
        Set-AuthenticodeSignature -FilePath $f -Certificate $cert -HashAlgorithm SHA256 | Out-Null
        Write-Output "signed $f (no timestamp)"
    }
}
