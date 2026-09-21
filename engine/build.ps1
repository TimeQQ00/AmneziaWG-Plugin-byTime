# Сборка движка libawgcore.so (Android arm64) и тестовой DLL под Windows.
#
#   .\build.ps1                # только Android-сборка (нужен Android NDK)
#   .\build.ps1 -Windows       # дополнительно собрать awgcore_test.dll (нужен zig)
#   .\build.ps1 -Ndk C:\path\to\ndk
#
param(
    [switch]$Windows,
    [string]$Ndk = $env:ANDROID_NDK_HOME
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$prebuilt = Join-Path $here 'prebuilt'

function Find-Ndk {
    param([string]$Hint)
    if ($Hint -and (Test-Path $Hint)) { return $Hint }
    foreach ($root in @('C:\awg-toolchain', "$env:LOCALAPPDATA\Android\Sdk\ndk", 'C:\Android\Sdk\ndk')) {
        if (Test-Path $root) {
            $candidate = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like 'android-ndk-*' } |
                Sort-Object Name -Descending | Select-Object -First 1
            if ($candidate) { return $candidate.FullName }
        }
    }
    return $null
}

# ---------- Android arm64 ----------
$ndk = Find-Ndk -Hint $Ndk
if (-not $ndk) {
    throw "Android NDK не найден. Укажите путь: .\build.ps1 -Ndk C:\path\to\android-ndk-r25c"
}
$clang = Join-Path $ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android21-clang.cmd'
if (-not (Test-Path $clang)) { throw "clang не найден: $clang" }

Push-Location $here
try {
    $env:GOOS = 'android'; $env:GOARCH = 'arm64'; $env:CGO_ENABLED = '1'; $env:CC = $clang
    $out = Join-Path $prebuilt 'libawgcore.so'
    go build -trimpath -ldflags "-s -w" -buildmode=c-shared -o $out .
    Write-Host ("[android/arm64] OK -> {0} ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB))
}
finally {
    Pop-Location
    Remove-Item Env:GOOS, Env:GOARCH, Env:CGO_ENABLED, Env:CC -ErrorAction SilentlyContinue
}

# ---------- Windows x64 (для тестов) ----------
if ($Windows) {
    $zig = (Get-Command zig -ErrorAction SilentlyContinue).Source
    if (-not $zig) {
        $pyzig = Join-Path (Split-Path -Parent $here) 'tools\pyzig\ziglang\zig.exe'
        if (Test-Path $pyzig) { $zig = $pyzig }
    }
    if (-not $zig) {
        throw "zig не найден (нужен для тестовой сборки). Установка: pip install ziglang"
    }

    Push-Location $here
    try {
        $env:GOOS = 'windows'; $env:GOARCH = 'amd64'; $env:CGO_ENABLED = '1'
        $env:CC = "$zig cc -target x86_64-windows-gnu"
        $dir = Join-Path $prebuilt 'windows-amd64'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $out = Join-Path $dir 'awgcore_test.dll'
        go build -buildmode=c-shared -o $out .
        Write-Host ("[windows/amd64] OK -> {0} ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB))
    }
    finally {
        Pop-Location
        Remove-Item Env:GOOS, Env:GOARCH, Env:CGO_ENABLED, Env:CC -ErrorAction SilentlyContinue
    }
}

Write-Host "Готово. Пересобрать плагин: python plugin\build.py"
