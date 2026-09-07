#!/usr/bin/env python3
"""Assemble self-contained facades, validating exactly the six host archives."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {f"{system}-{arch}" for system in ("linux", "macos", "windows")
           for arch in ("x86_64", "aarch64")}


def extract(archive, destination):
    # Packaging emits only regular files and directories, never links.
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                name = item.filename.replace("\\", "/")
                target = (destination / name).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError(f"unsafe archive member: {name}")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(item) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as source:
            for item in source:
                target = (destination / item.name).resolve()
                if not target.is_relative_to(destination.resolve()) or not (item.isfile() or item.isdir()):
                    raise ValueError(f"unsafe archive member: {item.name}")
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(item) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)


def build(archive_dir, output_dir, single_host=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    archives = {}
    for archive in archive_dir.rglob("qemu-*"):
        if not archive.is_file():
            continue
        suffix = ".zip" if archive.name.endswith(".zip") else ".tar.gz"
        if not archive.name.endswith(suffix):
            continue
        target = archive.name[5:-len(suffix)]
        if target not in TARGETS or target in archives:
            raise ValueError(f"unexpected or duplicate native archive: {archive}")
        archives[target] = archive
    if not archives or (not single_host and set(archives) != TARGETS):
        raise ValueError(f"expected six host archives, found {sorted(archives)}")
    with tempfile.TemporaryDirectory(prefix="qemu-facades-") as temporary:
        work = Path(temporary)
        resources = work / "resources"
        for target, archive in sorted(archives.items()):
            destination = resources / "native" / target
            destination.mkdir(parents=True)
            extract(archive, destination)
            payload = destination / "qemu"
            # Facades load libraries; keep CLI executables/import archives only
            # in the native downloads, not in both universal facade files.
            for file in (payload / "bin").iterdir():
                if file.name.startswith("qemu-system-") or file.name.endswith((".a", ".lib")):
                    file.unlink()
            suffix = ".dll" if target.startswith("windows") else ".dylib" if target.startswith("macos") else ".so"
            if not (payload / "bin" / f"libqemu_jni{suffix}").is_file():
                raise ValueError(f"missing JNI bridge in {archive}")
            guests = (payload / "guests.txt").read_text().splitlines()
            if not guests:
                raise ValueError(f"empty guest list in {archive}")
            for guest in guests:
                if not (payload / "bin" / f"libqemu-system-{guest}{suffix}").is_file():
                    raise ValueError(f"missing guest library: {guest} in {archive}")
            manifest = []
            for file in sorted(payload.rglob("*")):
                if file.is_file():
                    digest = hashlib.sha256(file.read_bytes()).hexdigest()
                    manifest.append(f"{digest}  {file.relative_to(destination).as_posix()}\n")
            (destination / "files.list").write_text("".join(manifest), encoding="utf-8")
            if archive.resolve() != (output_dir / archive.name).resolve():
                shutil.copy2(archive, output_dir / archive.name)
        classes = work / "classes"
        classes.mkdir()
        sources = sorted((ROOT / "bindings/jvm/src/main/java").rglob("*.java"))
        subprocess.run(["javac", "--release", "17", "-d", str(classes), *map(str, sources)], check=True)
        output_suffix = f"-{next(iter(archives))}" if single_host else ""
        subprocess.run(["jar", "--create", "--file", str(output_dir / f"qemu-cli{output_suffix}.jar"),
                        "--main-class", "org.qemu.cli.Main", "-C", str(classes), ".",
                        "-C", str(resources), "."], check=True)
        # Stream the same resources into the zipapp without duplicating several
        # gigabytes on the CI runner's disk. zipfile enables ZIP64 by default.
        with zipfile.ZipFile(output_dir / f"qemu{output_suffix}.pyz", "w", zipfile.ZIP_DEFLATED) as app:
            app.writestr("__main__.py", "from qemu.__main__ import main\nmain()\n")
            for file in sorted((ROOT / "bindings/python/qemu").glob("*.py")):
                app.write(file, "qemu/" + file.name)
            for file in sorted(resources.rglob("*")):
                if file.is_file():
                    app.write(file, "qemu/" + file.relative_to(resources).as_posix())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--single-host", action="store_true", help="local/CI smoke test only; release requires all six")
    args = parser.parse_args()
    build(args.archive_dir.resolve(), args.output_dir.resolve(), args.single_host)
