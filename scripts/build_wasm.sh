#!/bin/sh
# Build the wasm side module and its page agent modules.
#
#     scripts/build_wasm.sh [output directory]
#
# Built as hlwgpu builds xgpu.wasm: a position-independent
# standard library on nightly, the threaded WASI target for the mailbox's
# shared memory, and every primitive named as an export.
set -e

here=$(cd "$(dirname "$0")/.." && pwd)
# The Rust toolchain to build with, as rustup names it. See the guard at the end.
nightly=${RUST_NIGHTLY:-nightly}
out=${1:-"$here/target/wasm"}
mkdir -p "$out"
rm -f "$out/xavi.wasm" "$out/xavi.mjs" "$out/xavi_wire.mjs"

# The build script generates the page modules into its OUT_DIR, which cargo
# reports among its JSON messages.
messages=$(
  CARGO_PROFILE_RELEASE_LTO=false \
  CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
  RUSTFLAGS="-C relocation-model=pic -C target-feature=+mutable-globals -C panic=abort" \
    cargo +"$nightly" rustc -p hlavi --lib --crate-type staticlib \
      --target wasm32-wasip1-threads --release \
      -Z build-std=std,panic_abort --message-format=json-render-diagnostics
)
page=$(printf '%s\n' "$messages" \
  | grep '"reason":"build-script-executed"' | grep -E '/hlavi#|#hlavi@' \
  | sed -n 's/.*"out_dir":"\([^"]*\)".*/\1/p' | tail -1)/page
[ -f "$page/xavi.mjs" ] || { echo "no page modules in $page" >&2; exit 1; }
cp "$page/xavi.mjs" "$page/xavi_wire.mjs" "$out/"

lld=$(find "$(rustc +"$nightly" --print sysroot)/lib/rustlib" -name rust-lld -type f | head -1)
[ -n "$lld" ] || { echo "no rust-lld in the nightly sysroot" >&2; exit 1; }

# One resolver export per generated Haxe primitive. The file name is
# xavi.wasm because @:hlNative("xavi", ...) names the library.
exports=$(sed -n 's/.*@:hlNative("xavi", "\([^"]*\)").*/--export=hlp_\1/p' \
  "$here"/haxe/media/*.hx | sort -u)
[ -n "$exports" ] || { echo "no xavi primitives found in haxe/media" >&2; exit 1; }

# shellcheck disable=SC2086
"$lld" -flavor wasm \
  --experimental-pic -shared --no-entry \
  --unresolved-symbols=import-dynamic --gc-sections --no-export-dynamic \
  --shared-memory --max-memory=1073741824 \
  $exports \
  --whole-archive "$here/target/wasm32-wasip1-threads/release/libhlavi.a" --no-whole-archive \
  -o "$out/xavi.wasm"

# A newer nightly's std imports pthread keys, which Ash does not define: say so here, not when a program that loads it is built.
if grep -q pthread_key_create "$out/xavi.wasm"; then
  echo "build_wasm: $out/xavi.wasm imports pthread_key_create, which Ash does not define; this Rust nightly is too new. Build with RUST_NIGHTLY=nightly-2026-08-25." >&2
  exit 1
fi

echo "wrote $out/xavi.wasm ($(wc -c < "$out/xavi.wasm" | tr -d ' ') bytes), xavi.mjs and xavi_wire.mjs"

