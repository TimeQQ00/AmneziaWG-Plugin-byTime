#!/usr/bin/env bash
# Сборка движка libawgcore.so под Android arm64 (Linux / macOS).
#
#   ANDROID_NDK_HOME=/path/to/android-ndk-r25c ./build.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"

if [ -z "$NDK" ] || [ ! -d "$NDK" ]; then
    echo "Не найден Android NDK. Задайте ANDROID_NDK_HOME=/path/to/android-ndk" >&2
    exit 1
fi

HOST_TAG="linux-x86_64"
[ "$(uname)" = "Darwin" ] && HOST_TAG="darwin-x86_64"

CC="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin/aarch64-linux-android21-clang"
if [ ! -x "$CC" ]; then
    echo "clang не найден: $CC" >&2
    exit 1
fi

cd "$HERE"
GOOS=android GOARCH=arm64 CGO_ENABLED=1 CC="$CC" \
    go build -trimpath -ldflags "-s -w" -buildmode=c-shared \
    -o prebuilt/libawgcore.so .

ls -lh prebuilt/libawgcore.so
echo "Готово. Пересобрать плагин: python3 plugin/build.py"
