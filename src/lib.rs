//! Ash/HashLink primitives generated from xavi's shared media declaration.
//! One VM owns this loaded library's handle tables; handles can be passed among
//! its threads. Explicitly close media handles when no longer needed. Embedding
//! multiple independent VMs in one process needs a host context hook first.

// x-idl emits names and C signatures that mirror the Haxe/HashLink surface.
#![allow(
    dead_code,
    non_snake_case,
    improper_ctypes_definitions,
    unused_unsafe,
    clippy::all
)]
#![allow(unsafe_op_in_unsafe_fn)]

#[cfg(target_family = "wasm")]
compile_error!(
    "hlavi currently implements native hosts; the browser media adapter is not implemented"
);

mod runtime {
    pub use hl_xidl::*;

    pub mod host {
        use hl_xidl::ErrorKind;
        pub use hl_xidl::host::throw_pending;

        pub fn raise(kind: ErrorKind, message: &str) {
            let prefix = match kind {
                ErrorKind::Type => "Media type error: ",
                ErrorKind::Runtime => "Media error: ",
            };
            hl_xidl::host::raise(kind, &format!("{prefix}{message}"));
        }
    }
}

use runtime::{Buffer, BufferMut, Enum, ErrorKind, Future, NativeEnum, Rooted, Text, host};

// MediaBackend holds Rust snapshots, not guest pointers. It locks only its
// handle tables; the generated wrapper raises guest errors after calls return.
static MEDIA: xavi_backend::MediaBackend = xavi_backend::MediaBackend::new();

fn with_media<T>(operation: impl FnOnce(&xavi_backend::MediaBackend) -> T) -> T {
    operation(&MEDIA)
}

// Managed records root guest buffers through hl_xidl. Future results are set
// through the host ABI. All writes into the guest heap use GC-aware VM calls.
#[unsafe(no_mangle)]
pub static ash_hdll_barrier_aware: u8 = 1;

mod backend {
    include!(concat!(env!("OUT_DIR"), "/xavi_backend/native.rs"));
}

include!(concat!(env!("OUT_DIR"), "/media.rs"));
