WebAssembly modules are read by browsers, server-side runtimes, validators and security
scanners. Most sample modules are compiler output, which means megabytes of runtime you did
not ask for and a file nobody can read.

`wasm/minimal-add.wasm` is the opposite: a module exporting one function, `add(i32, i32) ->
i32`, assembled byte by byte rather than compiled. It carries no toolchain fingerprint, no
producers section and no debug information, so the file is small, stable, and the same on
every build.

It is enough for a host to instantiate the module and call the export, which is the operation
worth testing — not what a large module does, but whether your loader gets a small one right.
It is served as `application/wasm`, so it also checks that the content type survives your
pipeline, which matters because browsers refuse to stream-compile a module served as anything
else.

Use it to test module loading, instantiation, validation and content-type handling. Related
format: [binary files](/bin).
