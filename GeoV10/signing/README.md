# Code signing

The Geo exes are signed with a **self-signed** code-signing certificate
(`CN=BlackGoat Geo`). This gives every release a stable publisher identity and
makes it trusted on machines that have the public cert installed.

**What it does / does not do**
- ✅ On a VM/PC where `geo-codesign.cer` is installed in *Trusted Root* +
  *Trusted Publishers*, the exe is a trusted, signed app — good for the fleet you control.
- ❌ It does **not** earn Microsoft SmartScreen / Defender-cloud reputation for
  machines you don't control. Only an **OV/EV** certificate from a real CA does that.

## Files
- `geo-codesign.cer` — **public** cert. Safe to share. Install this on your VMs.
- `geo-codesign.pfx` — **private key. NEVER commit / share.** Kept out of git by `.gitignore`.
  Password is stored with you, not in the repo.

## Sign a build
```powershell
powershell -File sign.ps1 -Pfx <path-to>\geo-codesign.pfx -Password '<pw>' -Files ..\..\dist\app.exe
# or the C# exe:
powershell -File sign.ps1 -Pfx <path-to>\geo-codesign.pfx -Password '<pw>' -Files ..\bin\Release\net8.0-windows\win-x64\publish\app.exe
```

## Trust the cert on a VM (one-time, per machine — run as admin)
```powershell
Import-Certificate -FilePath geo-codesign.cer -CertStoreLocation Cert:\LocalMachine\Root
Import-Certificate -FilePath geo-codesign.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher
```
After that the app shows as a verified publisher on that machine. You can also
push these two commands via GPO / your VM provisioning so every new VM trusts it.
