use std::path::PathBuf;

fn main() {
    let out = PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    xavi_backend::install(&out).expect("installing xavi's shared native adapter");
    let model = xavi_bindgen::generate(xavi_bindgen::Runtime::HashLink)
        .expect("generating the Ash/HashLink media primitives");
    std::fs::write(out.join("media.rs"), model).expect("writing the media primitives");

    let root = PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    for file in xavi_bindgen::haxe(xavi_bindgen::haxe::Runtime::HashLink)
        .expect("generating the Haxe media API")
    {
        let path = root.join("haxe").join(file.path);
        if std::fs::read_to_string(&path).ok().as_deref() != Some(file.source.as_str()) {
            std::fs::create_dir_all(path.parent().unwrap()).expect("creating the Haxe package");
            std::fs::write(path, file.source).expect("writing the Haxe media API");
        }
    }
    // Removing generated sources should regenerate them even when dependencies
    // have not changed. Writes above preserve mtimes when content is unchanged.
    println!("cargo:rerun-if-changed=haxe/media");
    println!("cargo:rerun-if-changed=build.rs");
    match std::env::var("CARGO_CFG_TARGET_VENDOR").as_deref() {
        Ok("apple") => println!("cargo:rustc-cdylib-link-arg=-Wl,-undefined,dynamic_lookup"),
        _ if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") => {
            println!("cargo:rerun-if-env-changed=HL_LIB_DIR");
            if let Some(dir) = std::env::var_os("HL_LIB_DIR") {
                println!(
                    "cargo:rustc-link-search=native={}",
                    PathBuf::from(dir).display()
                );
                println!("cargo:rustc-link-lib=dylib=libhl");
            }
        }
        _ => {}
    }
}
