# QEMU native CLI bundles

The release workflow builds six host bundles: Linux, macOS and Windows, each
for x86_64 and aarch64. Every bundle contains **all system-emulation guests
supported by QEMU on that host**, listed in `qemu/guests.txt`. Host architecture
is independent of guest architecture. Linux-user/BSD-user emulation and helper
tools such as qemu-img are not part of these system-emulator facades.

Each guest has both a normal `qemu-system-<guest>` executable and a shared
library in `qemu/bin`: `libqemu-system-<guest>.so` on Linux, `.dylib` on macOS,
and `.dll` on Windows. The library exports both `main` and
`int dll_main(int argc, char **argv)` with the C calling convention. Both use
the same QEMU initialization, event loop, cleanup, and exit behavior. Supply
an argv[0] and a NULL-terminated argv array. The library locates firmware
relative to itself, even when loaded by Java or Python; keep the bundle intact.

## Running the facades

Requires Java 17+ or Python 3.10+. Each platform-specific facade contains the
native payload for its own OS/CPU architecture.

```sh
java -jar qemu-cli-linux-x86_64.jar --version
python3 qemu-linux-x86_64.pyz --version
QEMU_GUEST=riscv64 java -jar qemu-cli-linux-x86_64.jar -machine virt -display none -S
QEMU_GUEST=aarch64 python3 qemu-linux-x86_64.pyz -machine virt -cpu cortex-a57 -display none -S
```

On PowerShell, set e.g. `$env:QEMU_GUEST = 'riscv64'` before launching.
`QEMU_GUEST` defaults to the host architecture. This environment variable is
the only guest selector: every command-line argument, including `--`, empty
arguments, spaces and Unicode, is passed to dll_main without shell parsing or
facade-specific option processing. Java uses JNI and Python uses ctypes; the
facades call the shared library directly in their process.

QEMU owns process-wide state, signals and threads and normally calls `exit()`.
**Call only once per process; the call can terminate the JVM/Python process.**
This is a CLI interface, not a reusable or thread-safe VM embedding API. Native
exit does not run Java shutdown hooks or Python atexit handlers. The facades
therefore extract to a persistent, content-addressed cache instead of creating
an abandoned temporary directory on every run. The default cache is
`~/.cache/qemu-cli`; override it with `QEMU_CACHE_DIR`, or delete it when no
facade is running to reclaim space. Files are checked against SHA-256 manifests.
`QEMU_BUNDLE_DIR` can point directly to an already extracted `qemu/` directory
to skip embedded resource extraction (also used by development tests).

These are headless builds with TCG, VNC, slirp user networking, and standard
firmware. Use serial/monitor/QMP or VNC for interaction. Native GUI frontends,
hardware acceleration, loadable modules, plugins, and optional external storage
backends are disabled to keep the six bundles consistent. System libraries
(Linux glibc, macOS frameworks, Windows system DLLs) come from the host;
other dynamically linked dependencies are bundled alongside the emulator.
macOS bundles use TCG's interpreter backend (TCI), which is slower but avoids
requiring a second MAP_JIT region inside the JVM or JIT entitlements on Python.
Apple documents the one-region restriction here:
https://developer.apple.com/documentation/apple-silicon/porting-just-in-time-compilers-to-apple-silicon
Headless DLL-enabled macOS builds run the QEMU loop on the calling thread;
they do not need Cocoa's process-main-thread event loop.
Linux CI builds on Ubuntu 22.04 (glibc 2.35 baseline). macOS CI builds on
macOS 15. Windows CI uses MSYS2 CLANG64/CLANGARM64 on Windows 11/Server 2025.

## Building and publishing

Run `.github/workflows/release.yml` manually. With an empty `release_name`, it
only produces workflow artifacts. Supplying a tag also creates/updates that
GitHub release after every host passes its native and facade smoke tests.
Each host/CPU job publishes its native archive plus matching
`qemu-cli-<os>-<arch>.jar` and `qemu-<os>-<arch>.pyz`. Both contain only that
host's native payload. The jar also exposes `org.qemu.Qemu.run`.

The matrix builds natively on each OS/CPU runner rather than trying to cross
link macOS or Windows libraries on Linux. This permits actual FFI smoke tests
on all six platforms. The QEMU build itself cross-emulates every guest.
Runner labels: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
Windows environment: https://github.com/msys2/setup-msys2

For a local build (requires a C/C++ toolchain, make, Ninja, Python 3.12+, a JDK,
GLib, pixman, libfdt, slirp, zlib, flex and Bison 3+; Linux packaging also
requires patchelf, and macOS uses Homebrew plus libffi):

```sh
bash github-workflows-scripts/package-native.sh linux-x86_64 build/native
python3 github-workflows-scripts/build-launchers.py build/native build/assets --single-host
python3 github-workflows-scripts/smoke-test.py build/assets
```

Set `JAVA_HOME` to the JDK and optionally `JOBS` to bound parallel compilation.
`QEMU_TARGET_LIST=x86_64-softmmu,aarch64-softmmu` reduces a **local test** build;
the release workflow leaves it unset to include all system guests.
For custom Meson builds, use `-Dcli_dll=true -Db_staticpic=true` with GUI,
modules and plugins disabled. The shared-library option defaults to off.

QEMU license notices and dependency notices accompany each native bundle.
Redistributors must also meet the applicable source distribution obligations;
publishing a binary facade does not remove those obligations.
