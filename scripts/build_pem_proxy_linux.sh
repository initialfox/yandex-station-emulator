#!/usr/bin/env bash
# Link against the supplied firmware's ARM32 libraries, not host glibc.
set -euo pipefail
[[ $# == 2 ]] || { echo "Usage: $0 ARM32_LIBRARY_DIRECTORY OUTPUT_BINARY" >&2; exit 2; }
source_dir="$(cd "$(dirname "$0")/.." && pwd)"
library_dir="$(cd "$1" && pwd)"
compiler="${ARM32_CC:-arm-linux-gnueabihf-gcc}"
for library in libc.so.6 libcrypto.so.1.1; do
    [[ -f "$library_dir/$library" ]] || { echo "Missing firmware library: $library" >&2; exit 2; }
done
"$compiler" -O2 -fno-pie -no-pie -nostdlib -Wl,-e,_start \
    -Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3 -Wl,--allow-shlib-undefined \
    "$source_dir/qemu/mini2/optee/pem_proxy.c" \
    "$library_dir/libcrypto.so.1.1" "$library_dir/libc.so.6" -o "$2"
