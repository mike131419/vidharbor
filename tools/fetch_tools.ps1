# Downloads ffmpeg/ffprobe (yt-dlp's Windows builds) and Deno into -Dest.
param([string]$Dest = "bin")
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$tmp = Join-Path $env:TEMP ("vidharbor-tools-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

$downloads = @(
  @{ Url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"; Files = @("ffmpeg.exe", "ffprobe.exe") },
  @{ Url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"; Files = @("deno.exe") }
)
foreach ($d in $downloads) {
  $zip = Join-Path $tmp ([IO.Path]::GetFileName($d.Url))
  Write-Host "Downloading $($d.Url)"
  Invoke-WebRequest -Uri $d.Url -OutFile $zip
  $out = Join-Path $tmp ([IO.Path]::GetFileNameWithoutExtension($zip))
  Expand-Archive -Path $zip -DestinationPath $out -Force
  foreach ($f in $d.Files) {
    $found = Get-ChildItem -Path $out -Recurse -Filter $f | Select-Object -First 1
    if (-not $found) { throw "$f not found in $zip" }
    Copy-Item $found.FullName -Destination $Dest -Force
    Write-Host "  -> $Dest\$f"
  }
}
Remove-Item -Recurse -Force $tmp
