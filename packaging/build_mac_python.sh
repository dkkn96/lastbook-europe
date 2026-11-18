#!/bin/bash
# Builds a private CPython 3.11.18 with OpenSSL and liblzma for macOS 14 and Apple Silicon.
set -euo pipefail
ROOT="$(dirname "$(dirname "$(/bin/realpath "$0")")")"
CACHE="$ROOT/derived/mac-toolchain/sources"
mkdir -p "$CACHE"
WORK="$(mktemp -d "$ROOT/derived/mac-toolchain/build.XXXXXXXX")"
JOBS="$(sysctl -n hw.ncpu)"
export MACOSX_DEPLOYMENT_TARGET=14.0

fetch() {
  local name="$1" url="$2" sha="$3"
  if [ ! -f "$CACHE/$name" ]; then
    curl -q --fail --silent --show-error --location --retry 2 --max-time 480 \
      "$url" -o "$WORK/$name"
    printf '%s  %s\n' "$sha" "$WORK/$name" | shasum -a 256 -c
    mv "$WORK/$name" "$CACHE/$name"
  fi
  printf '%s  %s\n' "$sha" "$CACHE/$name" | shasum -a 256 -c
  tar -xf "$CACHE/$name" -C "$WORK"
}

fetch Python-3.11.18.tar.xz https://www.python.org/ftp/python/3.11.18/Python-3.11.18.tar.xz 9120e0a653868f6e3698d36cdd99e5a58903ec9469e448f21d98f7b16d8fa290
fetch openssl-3.5.9.tar.gz https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz 603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a
fetch xz-5.8.4.tar.gz https://github.com/tukaani-project/xz/releases/download/v5.8.4/xz-5.8.4.tar.gz 0014c7886930454fe8bd4228665b51af55eeae560ea135c9c4cd33f55b2591d9

cd "$WORK/openssl-3.5.9"
./Configure darwin64-arm64-cc no-shared no-tests --prefix=/usr/local --openssldir=/etc/ssl > "$WORK/openssl.log" 2>&1
make -j "$JOBS" >> "$WORK/openssl.log" 2>&1
make DESTDIR="$WORK/deps" install_sw >> "$WORK/openssl.log" 2>&1

cd "$WORK/xz-5.8.4"
CFLAGS="-O2 -g0 -ffile-prefix-map=$WORK=/build" \
  ./configure --disable-shared --enable-static --disable-nls --prefix=/usr/local > "$WORK/xz.log" 2>&1
make -j "$JOBS" >> "$WORK/xz.log" 2>&1
make DESTDIR="$WORK/deps" install >> "$WORK/xz.log" 2>&1

cd "$WORK/Python-3.11.18"
DEPS="$WORK/deps/usr/local"
PREFIX=/opt/lastbook-python
CFLAGS="-O2 -g0 -ffile-prefix-map=$WORK=/build" PKG_CONFIG=/usr/bin/false \
  LIBLZMA_CFLAGS="-I$DEPS/include" LIBLZMA_LIBS="$DEPS/lib/liblzma.a" \
  ./configure --prefix="$PREFIX" --enable-shared --without-ensurepip \
  --with-openssl="$DEPS" --with-openssl-rpath=no > "$WORK/python.log" 2>&1
make -j "$JOBS" >> "$WORK/python.log" 2>&1
make DESTDIR="$WORK" install >> "$WORK/python.log" 2>&1
RUNTIME="$WORK$PREFIX"
install_name_tool -id @rpath/libpython3.11.dylib "$RUNTIME/lib/libpython3.11.dylib"
install_name_tool -change "$PREFIX/lib/libpython3.11.dylib" @loader_path/../lib/libpython3.11.dylib "$RUNTIME/bin/python3.11"
codesign --force --sign - "$RUNTIME/lib/libpython3.11.dylib"
codesign --force --sign - "$RUNTIME/bin/python3.11"
"$RUNTIME/bin/python3.11" -c 'import hashlib, lzma, sqlite3, ssl, sys; print(sys.version, ssl.OPENSSL_VERSION)'
mkdir "$RUNTIME/licenses"
cp "$WORK/openssl-3.5.9/LICENSE.txt" "$RUNTIME/licenses/OpenSSL-LICENSE.txt"
cp "$WORK/xz-5.8.4/COPYING" "$RUNTIME/licenses/XZ-COPYING.txt"
ln -sfn "$RUNTIME" "$ROOT/derived/mac-toolchain/python"
echo "Built: $RUNTIME/bin/python3.11"
