#!/usr/bin/env python3
"""Bundle transitive runtime libraries and make their loader paths relocatable."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile


def command(*args):
    return subprocess.check_output(list(map(str, args)), text=True, stderr=subprocess.STDOUT)


def bundle(target, payload, output):
    system, architecture = target.split("-", 1)
    suffix = {"linux": ".so", "macos": ".dylib", "windows": ".dll"}[system]
    bindir = payload / "bin"
    guests = sorted(file.name[len("libqemu-system-"):-len(suffix)]
                    for file in bindir.glob(f"libqemu-system-*{suffix}"))
    if not guests or architecture not in guests:
        raise RuntimeError("missing system emulator libraries")
    (payload / "guests.txt").write_text("\n".join(guests) + "\n")
    if system == "macos":
        for unsigned in bindir.glob("qemu-system-*-unsigned"):
            if unsigned.with_name(unsigned.name.removesuffix("-unsigned")).is_file():
                unsigned.unlink()
    queue = [file for file in bindir.iterdir()
             if not file.name.endswith((".a", ".lib"))]
    seen = set()
    origins = {}
    windows_prefix = Path(command("cygpath", "-m", os.environ["MINGW_PREFIX"]).strip()) if system == "windows" else None
    while queue:
        binary = queue.pop()
        if binary in seen or not binary.is_file():
            continue
        seen.add(binary)
        dependencies = []
        if system == "linux":
            listing = command("ldd", binary)
            if "not found" in listing:
                raise RuntimeError(f"unresolved dependency for {binary}: {listing}")
            for line in listing.splitlines():
                match = re.match(r"\s*(\S+) => (/\S+)", line)
                if match and not re.match(r"lib(c|m|pthread|dl|rt|resolv|util)\.so\.", match[1]):
                    dependencies.append((match[1], Path(match[2])))
        elif system == "macos":
            for line in command("otool", "-L", binary).splitlines()[1:]:
                name = line.strip().split(" (", 1)[0]
                if name.startswith(("/usr/lib/", "/System/Library/")):
                    continue
                if name.startswith("@loader_path/"):
                    source = binary.parent / name[len("@loader_path/"):]
                elif name.startswith("@rpath/"):
                    candidates = [binary.parent / Path(name).name]
                    load_commands = command("otool", "-l", binary)
                    for rpath in re.findall(r"cmd LC_RPATH\n\s*cmdsize \d+\n\s*path (.*?) \(offset", load_commands):
                        candidates.append(Path(rpath.replace("@loader_path", str(binary.parent))) / name[7:])
                    source = next((p for p in candidates if p.is_file()), None)
                    if source is None:
                        raise RuntimeError(f"cannot resolve {name} for {binary}")
                else:
                    source = Path(name)
                if source.resolve() != binary.resolve():
                    dependencies.append((name, source))
        else:
            listing = command("llvm-objdump", "-p", binary)
            for name in re.findall(r"DLL Name:\s*(\S+)", listing):
                source = windows_prefix / "bin" / name
                if source.is_file():
                    dependencies.append((name, source))
                elif not (Path(os.environ["SYSTEMROOT"]) / "System32" / name).is_file() and not name.lower().startswith(("api-ms-", "ext-ms-")):
                    raise RuntimeError(f"unresolved Windows dependency: {name}")
        for name, source in dependencies:
            destination = bindir / source.name
            if destination != source and not destination.exists():
                shutil.copy2(source, destination, follow_symlinks=True)
                origins[destination.name] = str(source)
            queue.append(destination)
            if system == "macos":
                subprocess.run(["install_name_tool", "-change", name, "@loader_path/" + source.name, str(binary)], check=True)
        if system == "linux":
            subprocess.run(["patchelf", "--set-rpath", "$ORIGIN", str(binary)], check=True)
        elif system == "macos" and binary.suffix == ".dylib":
            subprocess.run(["install_name_tool", "-id", "@loader_path/" + binary.name, str(binary)], check=True)
    if system == "macos":
        for binary in sorted(seen):
            subprocess.run(["codesign", "--force", "--sign", "-", str(binary)], check=True)
    licenses = payload / "licenses" / "dependencies"
    licenses.mkdir(parents=True, exist_ok=True)
    (licenses / "origins.txt").write_text("".join(f"{name}: {path}\n" for name, path in sorted(origins.items())))
    # Retain package-manager copyright/license notices for bundled dependencies.
    for name, origin in origins.items():
        if system == "linux":
            # dpkg records the original path; ldd can print its usr-merged alias.
            candidates = [origin, str(Path(origin).resolve())]
            candidates += ["/usr" + p for p in candidates if p.startswith("/lib/")]
            candidates += [p[4:] for p in list(candidates) if p.startswith("/usr/lib/")]
            for candidate in dict.fromkeys(candidates):
                found = subprocess.run(["dpkg-query", "-S", candidate],
                                       capture_output=True, text=True)
                if found.returncode == 0:
                    listing = found.stdout
                    break
            else:
                raise RuntimeError(f"cannot find dependency package/license: {origin}")
            package = listing.split(": ", 1)[0].split(":", 1)[0]
            source = Path("/usr/share/doc") / package / "copyright"
            if source.is_file():
                shutil.copy2(source, licenses / (name + ".copyright"))
        elif system == "macos":
            path = Path(origin).resolve()
            cellar_root = path.parent.parent
            for source in cellar_root.glob("*"):
                if source.is_file() and source.name.upper().startswith(("COPYING", "LICENSE", "NOTICE", "AUTHORS")):
                    shutil.copy2(source, licenses / (name + "-" + source.name))
        else:
            # MSYS2 installs license directories separately from its binaries.
            source = windows_prefix / "share/licenses"
            if source.is_dir() and not (licenses / "msys2").exists():
                shutil.copytree(source, licenses / "msys2")
    output.mkdir(parents=True, exist_ok=True)
    if system == "windows":
        archive = output / f"qemu-{target}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            for file in sorted(payload.rglob("*")):
                if file.is_file():
                    stream.write(file, file.relative_to(payload.parent))
    else:
        archive = output / f"qemu-{target}.tar.gz"
        with tarfile.open(archive, "w:gz", dereference=True) as stream:
            stream.add(payload, arcname="qemu")
    print(archive)


if __name__ == "__main__":
    bundle(sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
