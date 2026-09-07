#!/usr/bin/env python3
"""Exercise every native guest, both exports, and actual VM startup via both FFIs."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings/python"))
from qemu import host_target  # noqa: E402


def native_child(library, symbol):
    # Each call must be isolated: QEMU --version itself calls exit().
    if os.name == "nt":
        directory = os.add_dll_directory(str(Path(library).parent))
    native = ctypes.CDLL(library)
    entry = getattr(native, symbol)
    entry.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
    entry.restype = ctypes.c_int
    argv = (ctypes.c_char_p * 3)(os.fsencode(library), b"--version", None)
    raise SystemExit(entry(2, argv))


def checked(command, env, cwd):
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0 or "QEMU emulator version" not in result.stdout:
        raise AssertionError(f"{command}: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def vm_test(command, guest, env, cwd):
    name = "ffi spaces café 🐧"
    machine = ["-machine", "pc"] if guest == "x86_64" else ["-machine", "virt", "-cpu", "cortex-a57"]
    if guest == "aarch64":
        machine += ["-bios", "edk2-aarch64-code.fd"]
    args = machine + ["-accel", "tcg", "-m", "256", "-display", "none", "-nodefaults",
                      "-S", "-name", name, "-qmp", "stdio"]
    process = subprocess.Popen(command + args, env=env, cwd=cwd, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8")
    messages = queue.Queue()

    def read_messages():
        for line in process.stdout:
            messages.put(json.loads(line))
        messages.put(None)

    threading.Thread(target=read_messages, daemon=True).start()

    def response(key):
        while True:
            message = messages.get(timeout=90)
            if message is None:
                raise AssertionError("QEMU closed QMP: " + process.stderr.read())
            if "error" in message:
                raise AssertionError(message)
            if key in message:
                return message[key]

    def execute(name):
        process.stdin.write(json.dumps({"execute": name}) + "\n")
        process.stdin.flush()
        return response("return")

    try:
        response("QMP")
        execute("qmp_capabilities")
        if execute("query-name")["name"] != name:
            raise AssertionError("Unicode/space argument was not forwarded intact")
        execute("cont")
        if not execute("query-status")["running"]:
            raise AssertionError("guest did not start")
        execute("stop")
        execute("quit")
        if process.wait(timeout=30) != 0:
            raise AssertionError(process.stderr.read())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def main(assets):
    target = host_target()
    spec = importlib.util.spec_from_file_location("assembly", ROOT / "github-workflows-scripts/build-launchers.py")
    assembly = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembly)
    suffix = ".dll" if target.startswith("windows") else ".dylib" if target.startswith("macos") else ".so"
    archive = assets / (f"qemu-{target}.zip" if target.startswith("windows") else f"qemu-{target}.tar.gz")
    with tempfile.TemporaryDirectory(prefix="qemu smoke café ") as temporary:
        work = Path(temporary)
        assembly.extract(archive, work)
        payload = work / "qemu"
        guests = (payload / "guests.txt").read_text().splitlines()
        env = dict(os.environ, QEMU_CACHE_DIR=str(work / "cache"))
        env.pop("QEMU_BUNDLE_DIR", None)
        env.pop("QEMU_GUEST", None)
        for guest in guests:
            executable = payload / "bin" / (f"qemu-system-{guest}.exe" if os.name == "nt" else f"qemu-system-{guest}")
            if os.name != "nt":
                executable.chmod(0o755)
            expected = checked([str(executable), "--version"], env, work)
            library = payload / "bin" / f"libqemu-system-{guest}{suffix}"
            for symbol in ("main", "dll_main"):
                actual = checked([sys.executable, str(Path(__file__).resolve()), "--native-child", str(library), symbol], env, work)
                if actual != expected:
                    raise AssertionError(f"{guest}: {symbol} differs from the native executable")
        commands = [["java", "-jar", str(assets / "qemu-cli.jar")], [sys.executable, str(assets / "qemu.pyz")]]
        # A small real DLL checks exact argv bytes/count/NULL termination and
        # a returning nonzero result independently of QEMU's option parser.
        probe = work / "argv probe" / "bin"
        probe.mkdir(parents=True)
        compiler = "clang" if os.name == "nt" else "cc"
        shared = ["-dynamiclib", "-fPIC"] if target.startswith("macos") else ["-shared"]
        if target.startswith("linux"):
            shared += ["-fPIC"]
        subprocess.run([compiler, *shared, str(ROOT / "bindings/tests/argv_probe.c"),
                        "-o", str(probe / f"libqemu-system-{target.split('-', 1)[1]}{suffix}")], check=True)
        shutil.copy2(payload / "bin" / f"libqemu_jni{suffix}", probe)
        probe_env = dict(env, QEMU_BUNDLE_DIR=str(probe.parent))
        for command in commands:
            result = subprocess.run(command + ["", "two words", '"quoted"', "back\\slash", "--", "café 🐧"],
                                    env=probe_env, cwd=work, capture_output=True, timeout=90)
            if result.returncode != 37:
                raise AssertionError(f"argv/result forwarding failed: {result}")
            checked(command + ["--version"], env, work)
            for guest in ("x86_64", "aarch64"):
                if guest not in guests:
                    continue
                guest_env = dict(env, QEMU_GUEST=guest)
                checked(command + ["--version"], guest_env, work)
                result = subprocess.run(command + ["-this-option-does-not-exist"], env=guest_env,
                                        cwd=work, capture_output=True, text=True, timeout=90)
                if result.returncode == 0 or "invalid option" not in result.stderr:
                    raise AssertionError(f"CLI errors not propagated: {result}")
                vm_test(command, guest, guest_env, work)
        print(f"PASS: {target}, {len(guests)} guests, main + dll_main, JNI + ctypes, QMP/TCG/firmware/Unicode")


if __name__ == "__main__":
    if sys.argv[1] == "--native-child":
        native_child(sys.argv[2], sys.argv[3])
    else:
        main(Path(sys.argv[1]).resolve())
