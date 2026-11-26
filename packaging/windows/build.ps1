# Build the Windows installer: packaging\dist\Hypnomix-<version>-windows-x64-setup.exe
# It installs for the current user (no administrator needed): its own Python, hypnomix (with the Assistant and
# Listening extras), ffmpeg, Start menu entries, and optionally copies the AbletonOSC remote script into Live.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# Needs uv (https://docs.astral.sh/uv/) and Inno Setup 6 (iscc.exe; preinstalled on GitHub's Windows runners).
# Optional signing: set HYPNOMIX_SIGNTOOL to a full signtool command line, e.g.
#   signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f cert.pfx /p PASSWORD
$ErrorActionPreference = "Stop"
$PyVer = if ($env:HYPNOMIX_PYTHON) { $env:HYPNOMIX_PYTHON } else { "3.12" }
$Extras = "assistant,critique"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path "$Here\..\..").Path
$Version = (Select-String -Path "$Repo\pyproject.toml" -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
$Work = "$Repo\packaging\build\windows-x64"
$App = "$Work\Hypnomix"
$Dist = "$Repo\packaging\dist"
Write-Host "== hypnomix $Version for Windows x64"
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force -Path $App, $Dist, "$App\bin" | Out-Null

Write-Host "-- Python $PyVer (python-build-standalone, through uv)"
$env:UV_PYTHON_INSTALL_DIR = "$Work\pythons"
uv python install --no-bin "cpython-$PyVer-windows-x86_64-none" | Out-Null
if ($LASTEXITCODE) { throw "uv python install failed" }
$Src = Get-ChildItem "$Work\pythons" -Directory | Where-Object Name -like "cpython-$PyVer*-windows-x86_64-none" | Select-Object -First 1
if (-not $Src) { throw "uv did not install Python $PyVer" }
Copy-Item -Recurse $Src.FullName "$App\python"
Remove-Item -Recurse -Force "$Work\pythons"
Remove-Item Env:UV_PYTHON_INSTALL_DIR
$Py = "$App\python\python.exe"
Remove-Item -Force -ErrorAction SilentlyContinue "$App\python\Lib\EXTERNALLY-MANAGED"
# tkinter and tcl are left out on purpose (about 15 MB, and the app is a local web page): the installed Windows app has no
# file chooser, so its Songs page shows only the Path boxes (docs/APP.md). Keeping the chooser means keeping both Lib\tkinter and python\tcl.
foreach ($d in "test", "idlelib", "tkinter", "turtledemo", "ensurepip") {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$App\python\Lib\$d"
}
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$App\python\tcl"

Write-Host "-- hypnomix and its packages"
uv pip install --quiet --python $Py --no-cache --only-binary llvmlite --only-binary numba "$Repo[$Extras]" imageio-ffmpeg pip   # pip: Setup -> Extras installs the other extras with it
if ($LASTEXITCODE) { throw "uv pip install failed" }

Write-Host "-- ffmpeg"
$Ff = Get-ChildItem "$App\python\Lib\site-packages\imageio_ffmpeg\binaries" -Filter "ffmpeg-*.exe" | Select-Object -First 1
if (-not $Ff) { throw "no ffmpeg binary in imageio-ffmpeg" }
Copy-Item $Ff.FullName "$App\bin\ffmpeg.exe"
uv pip uninstall --quiet --python $Py imageio-ffmpeg
Remove-Item -Force -ErrorAction SilentlyContinue "$App\python\Scripts\hypnomix.exe"   # points at this build folder

Write-Host "-- launcher and icon"
Copy-Item "$Here\launcher.pyw" "$App\launcher.pyw"
& $Py "$Repo\macapp\icon.py" "$App\hypnomix.ico"
if ($LASTEXITCODE) { throw "icon failed" }
Copy-Item "$Repo\LICENSE" "$App\LICENSE.txt"
Copy-Item "$Repo\THIRD_PARTY.md" "$App\THIRD_PARTY.txt"

Write-Host "-- compiling Python files ahead"
Get-ChildItem -Path "$App\python" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
& $Py -m compileall -q -j 0 "$App\python\Lib" | Out-Null

Write-Host "-- installer (Inno Setup)"
$Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $Iscc)) { throw "Inno Setup 6 (iscc.exe) not found: https://jrsoftware.org/isdl.php" }
$SignArgs = @()
if ($env:HYPNOMIX_SIGNTOOL) { $SignArgs = @("/Ssigntool=$($env:HYPNOMIX_SIGNTOOL) `$f", "/DSIGN=1") }
& $Iscc /Q "/DAppVersion=$Version" "/DSourceDir=$App" "/DOutDir=$Dist" @SignArgs "$Here\hypnomix.iss"
if ($LASTEXITCODE) { throw "iscc failed" }
$Out = "$Dist\Hypnomix-$Version-windows-x64-setup.exe"
Write-Host ("built $Out ({0:N0} MB)" -f ((Get-Item $Out).Length / 1MB))
