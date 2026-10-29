$ErrorActionPreference = 'Stop'
$repo = 'felipemeriga/kioku'
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
    throw 'This release supports Windows x64. ARM users need an x64-compatible environment.'
}
$version = $env:KIOKU_VERSION
if (-not $version) {
    $releases = Invoke-RestMethod "https://api.github.com/repos/$repo/releases?per_page=100"
    $release = $releases | Where-Object { -not $_.draft -and -not $_.prerelease -and $_.tag_name -match '^cli-v\d+\.\d+\.\d+$' } | Select-Object -First 1
    if (-not $release) { throw 'No CLI release found; set KIOKU_VERSION explicitly.' }
    $version = $release.tag_name.Substring(5)
}
if ($version -notmatch '\A\d+\.\d+\.\d+(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?\z') { throw 'Invalid release version' }
$base = "https://github.com/$repo/releases/download/cli-v$version"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $binary = Join-Path $temp 'kioku.exe'
    Invoke-WebRequest "$base/kioku-windows-x64.exe" -OutFile $binary
    $sums = (Invoke-WebRequest "$base/SHA256SUMS").Content
    $line = ($sums -split "`n" | Where-Object { $_ -match '^[a-f0-9]{64}  kioku-windows-x64\.exe\s*$' })
    if (-not $line -or $line.Count -gt 1) { throw 'Missing or ambiguous checksum' }
    if ((Get-FileHash $binary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $line.Substring(0,64)) { throw 'Checksum verification failed' }
    & $binary --version
    if ($LASTEXITCODE -ne 0) { throw 'Executable smoke check failed' }
    $bin = if ($env:KIOKU_INSTALL_DIR) { $env:KIOKU_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\Kioku' }
    New-Item -ItemType Directory -Path $bin -Force | Out-Null
    Move-Item $binary (Join-Path $bin 'kioku.exe') -Force
    & (Join-Path $bin 'kioku.exe') internal-manabi-refresh
    if ($LASTEXITCODE -ne 0) { throw 'Kioku installed, but Manabi could not be refreshed. Run kioku init to repair it.' }
    $path = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (($path -split ';') -notcontains $bin) { [Environment]::SetEnvironmentVariable('Path', "$path;$bin", 'User') }
    Write-Host "Installed Kioku $version. Open a new terminal to use kioku."
} finally { Remove-Item $temp -Recurse -Force }
