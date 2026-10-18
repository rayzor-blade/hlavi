//! Ash/HashLink primitives generated from xavi's shared media declaration.
//! One VM owns this loaded library's handle tables; handles can be passed among
//! its threads. Explicitly close media handles when no longer needed. Embedding
//! multiple independent VMs in one process needs a host context hook first.
//!
//! For wasm it builds the side module `xavi.wasm`, whose media player is an
//! audio element in the page, served by the agent the host starts through
//! `ash_host_agent("xavi", block)`. The rest of the surface is not in a page yet.

// x-idl emits names and C signatures that mirror the Haxe/HashLink surface.
#![allow(
    dead_code,
    non_snake_case,
    improper_ctypes_definitions,
    unused_unsafe,
    unused_parens,
    clippy::all
)]
#![allow(unsafe_op_in_unsafe_fn)]
#![cfg_attr(
    all(target_arch = "wasm32", target_feature = "atomics"),
    feature(stdarch_wasm_atomic_wait, thread_local)
)]

#[cfg(target_family = "wasm")]
#[global_allocator]
static ALLOCATOR: hl_abi::ProgramAllocator = hl_abi::ProgramAllocator;

// As in hlwgpu: a side module cannot import the TLS errno threaded WASI's
// std addresses, and nothing here reports through it.
#[cfg(target_family = "wasm")]
#[unsafe(no_mangle)]
#[cfg_attr(target_feature = "atomics", thread_local)]
static mut errno: i32 = 0;

mod runtime {
    pub use hl_xidl::*;

    pub mod host {
        use hl_xidl::ErrorKind;
        #[cfg(target_family = "wasm")]
        pub use hl_xidl::host::agent;
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
#[cfg(not(target_family = "wasm"))]
static MEDIA: xavi_backend::MediaBackend = xavi_backend::MediaBackend::new();

#[cfg(not(target_family = "wasm"))]
fn with_media<T>(operation: impl FnOnce(&xavi_backend::MediaBackend) -> T) -> T {
    operation(&MEDIA)
}

// Managed records root guest buffers through hl_xidl. Future results are set
// through the host ABI. All writes into the guest heap use GC-aware VM calls.
#[unsafe(no_mangle)]
pub static ash_hdll_barrier_aware: u8 = 1;

#[cfg(not(target_family = "wasm"))]
mod backend {
    include!(concat!(env!("OUT_DIR"), "/xavi_backend/native.rs"));
}

#[cfg(target_family = "wasm")]
#[allow(dead_code, non_camel_case_types, unused_variables)]
mod wire {
    include!(concat!(env!("OUT_DIR"), "/media_wire.rs"));
}

#[cfg(target_family = "wasm")]
mod web {
    include!(concat!(env!("OUT_DIR"), "/xavi_backend/web.rs"));
}

#[cfg(target_family = "wasm")]
mod backend {
    use super::*;
    include!(concat!(env!("OUT_DIR"), "/media_web_backend.rs"));
}

include!(concat!(env!("OUT_DIR"), "/media.rs"));
