$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install 'pyinstaller==6.16.0' 'lz4==4.4.4'
if ($LASTEXITCODE -ne 0) { throw 'Python build dependencies failed' }
cmake -S . -B build/windows -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed' }
cmake --build build/windows --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
python -m PyInstaller --noconfirm --clean --onedir --console --name wallpaper-backend --paths . --distpath build/backend-dist --workpath build/backend-work --specpath build packaging/backend_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Python backend packaging failed' }
$Stage = Join-Path (Get-Location) 'dist/windows'
New-Item -ItemType Directory -Force $Stage | Out-Null
Copy-Item 'build/windows/Release/wallpaper-changer.exe' $Stage
Copy-Item 'build/backend-dist/wallpaper-backend' (Join-Path $Stage '_backend') -Recurse -Force
windeployqt --release --no-translations --qmldir qml (Join-Path $Stage 'wallpaper-changer.exe')
if ($LASTEXITCODE -ne 0) { throw 'Qt deployment failed' }

# Chocolatey's official ffmpeg package installs the actual tools under lib, not its shim directory.
$FFmpeg = Get-ChildItem "$env:ChocolateyInstall/lib/ffmpeg" -Recurse -Filter ffmpeg.exe | Select-Object -First 1
if (-not $FFmpeg) { throw 'FFmpeg executable was not installed' }
$Tools = Join-Path $Stage 'tools'
New-Item -ItemType Directory -Force $Tools | Out-Null
Copy-Item $FFmpeg.FullName $Tools
Copy-Item (Join-Path $FFmpeg.DirectoryName 'ffprobe.exe') $Tools
New-Item -ItemType Directory -Force (Join-Path $Stage 'licenses') | Out-Null
Get-ChildItem "$env:ChocolateyInstall/lib/ffmpeg" -Recurse -File | Where-Object { $_.Name -match 'LICENSE|COPYING|README' } | ForEach-Object { Copy-Item $_.FullName (Join-Path $Stage 'licenses') -Force }
if ($env:QT_ROOT_DIR) {
    Get-ChildItem "$env:QT_ROOT_DIR/../../Licenses" -File -ErrorAction SilentlyContinue | Copy-Item -Destination (Join-Path $Stage 'licenses') -Force
}
Copy-Item THIRD_PARTY_NOTICES.md (Join-Path $Stage 'licenses')
Copy-Item 'packaging/licenses/*.txt' (Join-Path $Stage 'licenses')
$PythonLicense = python -c 'import pathlib,sys; print(pathlib.Path(sys.base_prefix)/"LICENSE.txt")'
if (Test-Path $PythonLicense) { Copy-Item $PythonLicense (Join-Path $Stage 'licenses/Python-LICENSE.txt') }
$VSWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$VS = & $VSWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$CRT = Get-ChildItem "$VS/VC/Redist/MSVC/*/x64/Microsoft.VC143.CRT/*.dll" -ErrorAction SilentlyContinue
if (-not $CRT) { throw 'MSVC app-local runtime files were not found' }
$CRT | Copy-Item -Destination $Stage -Force
Copy-Item README.md $Stage
& (Join-Path $Tools 'ffmpeg.exe') -version | Out-File (Join-Path $Stage 'licenses/ffmpeg-build.txt') -Encoding utf8
@'
Qt 6.8.3 source: https://download.qt.io/archive/qt/6.8/6.8.3/single/
FFmpeg source/build instructions: https://github.com/GyanD/codexffmpeg
Python: https://www.python.org/downloads/source/
python-lz4: https://github.com/python-lz4/python-lz4
PyInstaller: https://github.com/pyinstaller/pyinstaller
The separate Qt DLLs may be replaced with compatible builds.
'@ | Out-File (Join-Path $Stage 'licenses/SOURCES.txt') -Encoding utf8

& (Join-Path $Stage 'wallpaper-changer.exe') --self-test
if ($LASTEXITCODE -ne 0) { throw 'Packaged backend self-test failed' }
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_QUICK_BACKEND = 'software'
$Smoke = Start-Process -FilePath (Join-Path $Stage 'wallpaper-changer.exe') -ArgumentList @('--smoke-test', 'build/windows-smoke') -Wait -PassThru
if ($Smoke.ExitCode -ne 0) { throw 'Packaged UI smoke test failed' }
Remove-Item Env:QT_QPA_PLATFORM
Remove-Item Env:QT_QUICK_BACKEND
Compress-Archive -Path "$Stage/*" -DestinationPath 'dist/wallpaper-changer-7.41f+Trove_of_Terror-windows-x86_64-portable.zip' -Force
$Inno = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
& $Inno 'packaging/windows.iss'
if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed' }

# Exercise the installer and the installed program, not only the staging directory.
$Installer = Get-ChildItem dist -Filter '*-setup.exe' | Select-Object -First 1
$Destination = Join-Path $env:RUNNER_TEMP 'WallpaperChangerInstalled'
$OriginalUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$Install = Start-Process -FilePath $Installer.FullName -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$Destination") -Wait -PassThru
if ($Install.ExitCode -ne 0) { throw 'Silent install failed' }
$InstalledPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not ((';' + $InstalledPath + ';').Contains(';' + $Destination + ';'))) { throw 'Installer did not register the terminal command' }
$Installed = Start-Process -FilePath (Join-Path $Destination 'wallpaper-changer.exe') -ArgumentList '--self-test' -Wait -PassThru
if ($Installed.ExitCode -ne 0) { throw 'Installed application self-test failed' }
$Uninstall = Start-Process -FilePath (Join-Path $Destination 'unins000.exe') -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
if ($Uninstall.ExitCode -ne 0) { throw 'Silent uninstall failed' }
if ([Environment]::GetEnvironmentVariable('Path', 'User') -cne $OriginalUserPath) { throw 'Uninstaller changed the original user PATH' }
