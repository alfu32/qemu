"""One-shot ctypes access to QEMU's dll_main(argc, argv)."""

import ctypes
import hashlib
import importlib.resources
import os
from pathlib import Path, PurePosixPath
import platform
import tempfile

_called = False
_library = None
_dll_directory = None


def host_target():
    system = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine().lower())
    if os.name == "nt":
        # platform.machine() describes the physical CPU on Windows. An x64
        # Python under ARM64 emulation must load the x64 DLL instead.
        process_machine, native_machine = ctypes.c_ushort(), ctypes.c_ushort()
        query = ctypes.WinDLL("kernel32", use_last_error=True).IsWow64Process2
        query.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)]
        query.restype = ctypes.c_int
        if not query(ctypes.c_void_p(-1), ctypes.byref(process_machine), ctypes.byref(native_machine)):
            raise ctypes.WinError(ctypes.get_last_error())
        arch = {0x8664: "x86_64", 0xAA64: "aarch64"}.get(process_machine.value or native_machine.value)
    if not system or not arch:
        raise RuntimeError(f"unsupported QEMU host: {platform.system()}/{platform.machine()}")
    return f"{system}-{arch}"


def _bundle(target):
    override = os.environ.get("QEMU_BUNDLE_DIR")
    if override:
        return Path(override).resolve()
    resources = importlib.resources.files(__package__).joinpath("native", target)
    manifest = resources.joinpath("files.list").read_bytes()
    identity = hashlib.sha256(manifest).hexdigest()
    cache = Path(os.environ.get("QEMU_CACHE_DIR", Path.home() / ".cache" / "qemu-cli"))
    root = cache / target / identity
    root.mkdir(parents=True, exist_ok=True)
    for line in manifest.decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise RuntimeError(f"unsafe native resource: {name}")
        output = root.joinpath(*relative.parts)
        if output.is_file() and hashlib.sha256(output.read_bytes()).hexdigest() == digest:
            continue
        data = resources.joinpath(*relative.parts).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError(f"corrupt native resource: {name}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return root / "qemu"


def run(arguments, guest=None):
    """Forward arguments unchanged; QEMU may exit the calling process."""
    global _called, _library, _dll_directory
    if _called:
        raise RuntimeError("QEMU dll_main may only be called once per process")
    target = host_target()
    guest = guest or os.environ.get("QEMU_GUEST", target.split("-", 1)[1])
    if not guest or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in guest):
        raise ValueError("invalid QEMU_GUEST")
    root = _bundle(target)
    suffix = ".dll" if os.name == "nt" else ".dylib" if target.startswith("macos-") else ".so"
    library = root / "bin" / f"libqemu-system-{guest}{suffix}"
    if not library.is_file():
        raise RuntimeError(f"guest {guest!r} is not included in {root}")
    encoded = [os.fsencode(library)]
    for argument in arguments:
        value = os.fsencode(argument)
        if b"\0" in value:
            raise ValueError("QEMU arguments cannot contain NUL")
        encoded.append(value)
    buffers = [ctypes.create_string_buffer(value) for value in encoded]
    argv = (ctypes.c_char_p * (len(buffers) + 1))()
    for i, buffer in enumerate(buffers):
        argv[i] = ctypes.cast(buffer, ctypes.c_char_p)
    if os.name == "nt":
        _dll_directory = os.add_dll_directory(str(root / "bin"))
    _library = ctypes.CDLL(str(library))
    entry = _library.dll_main
    entry.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
    entry.restype = ctypes.c_int
    _called = True
    return entry(len(buffers), argv)
