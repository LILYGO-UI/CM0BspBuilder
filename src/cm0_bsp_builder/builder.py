from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from collections.abc import Callable
from typing import Any

from . import __version__
from .image import ImageSource, Partition, copy_partition, parse_partitions, select_root_partition


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    development_packages: tuple[str, ...]
    export_paths: tuple[str, ...]
    required_paths: tuple[str, ...]


@dataclass(frozen=True)
class BuildResult:
    output_dir: Path
    sysroot_dir: Path
    archive: Path
    checksum: Path
    manifest: Path


def load_profile(name_or_path: str = "base") -> Profile:
    candidate = Path(name_or_path).expanduser()
    if candidate.is_file():
        data = json.loads(candidate.read_text(encoding="utf-8"))
    else:
        profile_name = name_or_path.removesuffix(".json")
        resource = resources.files("cm0_bsp_builder").joinpath(
            "profiles", f"{profile_name}.json"
        )
        if not resource.is_file():
            raise BuildError(f"unknown BSP profile: {name_or_path}")
        data = json.loads(resource.read_text(encoding="utf-8"))

    if data.get("schema_version") != 1:
        raise BuildError("unsupported profile schema_version")
    for key in ("name", "description", "development_packages", "export_paths", "required_paths"):
        if key not in data:
            raise BuildError(f"profile is missing {key}")

    export_paths = tuple(_safe_relative_path(item) for item in data["export_paths"])
    required_paths = tuple(_safe_relative_path(item) for item in data["required_paths"])
    return Profile(
        name=str(data["name"]),
        description=str(data["description"]),
        development_packages=tuple(str(item) for item in data["development_packages"]),
        export_paths=export_paths,
        required_paths=required_paths,
    )


def _safe_relative_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise BuildError(f"profile path must stay relative: {value}")
    return path.as_posix().lstrip("./")


def find_debugfs(explicit: str | None = None) -> Path:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    located = shutil.which("debugfs")
    if located:
        candidates.append(located)
    candidates.extend(
        [
            "/opt/homebrew/opt/e2fsprogs/sbin/debugfs",
            "/usr/local/opt/e2fsprogs/sbin/debugfs",
            "/usr/sbin/debugfs",
            "/sbin/debugfs",
        ]
    )
    for value in candidates:
        path = Path(value).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path.resolve()
    raise BuildError(
        "debugfs was not found; install e2fsprogs (brew install e2fsprogs or "
        "apt install e2fsprogs)"
    )


def inspect_source(path: str | Path) -> tuple[ImageSource, list[Partition], Partition]:
    source = ImageSource(path)
    partitions = parse_partitions(source.read_prefix(), source.image_size)
    return source, partitions, select_root_partition(partitions)


def extract_rootfs(debugfs: Path, filesystem_image: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    command = f'rdump / "{_debugfs_escape(destination)}"'
    result = subprocess.run(
        [str(debugfs), "-R", command, str(filesystem_image)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise BuildError(
            f"debugfs failed with exit code {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    if not (destination / "etc").is_dir() or not (destination / "usr").is_dir():
        raise BuildError(
            "debugfs did not produce a recognizable Linux root filesystem; "
            f"stderr: {result.stderr.strip()}"
        )


def _debugfs_escape(path: Path) -> str:
    value = str(path.resolve())
    if "\n" in value or "\r" in value:
        raise BuildError("work path contains a newline")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def export_sysroot(source_root: Path, destination: Path, profile: Profile) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for relative in profile.export_paths:
        source = source_root / relative
        if not os.path.lexists(source):
            continue
        target = destination / relative
        _copy_entry(source, target)
        copied.append(relative)
    return copied


def _copy_entry(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        if os.path.lexists(target):
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.symlink_to(os.readlink(source))
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target, follow_symlinks=False)


def overlay_debs(deb_dir: Path, sysroot: Path, profile: Profile, work_dir: Path) -> list[dict[str, str]]:
    packages = sorted(deb_dir.glob("*.deb"))
    if not packages:
        raise BuildError(f"no .deb files found in {deb_dir}")
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb:
        raise BuildError("dpkg-deb is required when --deb-dir is used")

    overlay_root = work_dir / "deb-overlay"
    overlay_root.mkdir()
    result: list[dict[str, str]] = []
    for package in packages:
        process = subprocess.run(
            [dpkg_deb, "-x", str(package), str(overlay_root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            raise BuildError(f"failed to extract {package.name}: {process.stderr.strip()}")
        result.append({"file": package.name, "sha256": sha256_file(package)})
    export_sysroot(overlay_root, sysroot, profile)
    return result


def validate_sysroot(sysroot: Path, profile: Profile) -> list[str]:
    return [relative for relative in profile.required_paths if not (sysroot / relative).exists()]


def parse_dpkg_status(status_file: Path) -> list[dict[str, str]]:
    if not status_file.is_file():
        return []
    packages: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in status_file.read_text(encoding="utf-8", errors="replace").splitlines() + [""]:
        if not line:
            if current.get("Status") == "install ok installed" and current.get("Package"):
                packages.append(
                    {
                        "package": current["Package"],
                        "version": current.get("Version", ""),
                        "architecture": current.get("Architecture", ""),
                    }
                )
            current = {}
            continue
        if line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in {"Package", "Version", "Architecture", "Status"}:
            current[key] = value.strip()
    return sorted(packages, key=lambda item: item["package"])


def parse_os_release(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip().strip('"')
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_archive(sysroot: Path, destination: Path) -> None:
    if destination.exists():
        raise BuildError(f"refusing to overwrite BSP archive: {destination}")
    with destination.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                archive.add(sysroot, arcname=".", recursive=True, filter=_normalize_tar_info)


def _normalize_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    info.pax_headers = {}
    return info


def build_bsp(
    input_path: Path,
    output_dir: Path,
    profile: Profile,
    debugfs_path: str | None = None,
    deb_dir: Path | None = None,
    work_dir: Path | None = None,
    keep_work: bool = False,
    allow_incomplete: bool = False,
    progress: Callable[[str], None] | None = None,
) -> BuildResult:
    notify = progress or (lambda _message: None)
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    notify("Inspecting image partition table")
    source, partitions, root_partition = inspect_source(input_path)
    debugfs = find_debugfs(debugfs_path)

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        if keep_work:
            work_dir = output_dir / "work"
            work_dir.mkdir(exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="cm0-bsp-")
            work_dir = Path(temporary.name)
    else:
        work_dir = work_dir.expanduser().resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        if any(work_dir.iterdir()):
            raise BuildError(f"work directory is not empty: {work_dir}")

    try:
        if source.compressed:
            notify(f"Extracting {source.image_name} from ZIP")
        image_path = source.extract_image(work_dir / source.image_name)
        root_partition_image = work_dir / "rootfs.ext4"
        notify(
            f"Copying root partition {root_partition.index} "
            f"({root_partition.size_bytes / (1024**3):.2f} GiB)"
        )
        copy_partition(image_path, root_partition, root_partition_image)
        extracted_rootfs = work_dir / "rootfs"
        notify("Extracting ext4 root filesystem with debugfs")
        extract_rootfs(debugfs, root_partition_image, extracted_rootfs)

        sysroot = output_dir / "sysroot"
        notify(f"Exporting {profile.name} sysroot files")
        copied_paths = export_sysroot(extracted_rootfs, sysroot, profile)
        overlay_packages: list[dict[str, str]] = []
        if deb_dir is not None:
            notify(f"Overlaying development packages from {deb_dir}")
            overlay_packages = overlay_debs(
                deb_dir.expanduser().resolve(), sysroot, profile, work_dir
            )

        # Import here to keep the project helper's BuildError dependency acyclic.
        from .project import install_toolchain

        toolchain = install_toolchain(sysroot)

        notify("Validating required headers, libraries, and pkg-config files")
        missing = validate_sysroot(sysroot, profile)
        try:
            source_date_epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
        except ValueError as error:
            raise BuildError("SOURCE_DATE_EPOCH must be an integer") from error

        manifest_data: dict[str, Any] = {
            "schema_version": 1,
            "builder": {"name": "cm0-bsp-builder", "version": __version__},
            "source_date_epoch": source_date_epoch,
            "source": {
                "file": input_path.name,
                # Hash the exact released container, not the temporary IMG.
                "sha256": sha256_file(input_path),
                "image_name": source.image_name,
                "image_size": source.image_size,
                "partitions": [item.to_dict() for item in partitions],
                "root_partition": root_partition.to_dict(),
            },
            "target": {
                "architecture": "aarch64",
                "multiarch": "aarch64-linux-gnu",
                "os_release": parse_os_release(extracted_rootfs / "etc/os-release"),
            },
            "sdk": {
                "cmake_toolchain": toolchain.relative_to(sysroot).as_posix(),
            },
            "profile": {
                "name": profile.name,
                "description": profile.description,
                "development_packages": list(profile.development_packages),
                "copied_paths": copied_paths,
                "missing_required_paths": missing,
            },
            "overlay_packages": overlay_packages,
            "installed_packages": parse_dpkg_status(
                extracted_rootfs / "var/lib/dpkg/status"
            ),
        }
        manifest_dir = sysroot / "usr/share/cm0-bsp"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = manifest_dir / "manifest.json"
        manifest.write_text(
            json.dumps(manifest_data, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        if missing and not allow_incomplete:
            formatted = "\n  ".join(missing)
            packages = " ".join(profile.development_packages)
            raise BuildError(
                "sysroot is incomplete for profile "
                f"{profile.name}; missing:\n  {formatted}\n"
                f"Download the development packages and rerun with --deb-dir. "
                f"Suggested packages: {packages}"
            )

        archive = output_dir / "sdk_bsp.tar.gz"
        notify("Creating reproducible sdk_bsp.tar.gz")
        create_archive(sysroot, archive)
        notify("Writing archive SHA-256")
        archive_hash = sha256_file(archive)
        checksum = output_dir / "sdk_bsp.tar.gz.sha256"
        checksum.write_text(f"{archive_hash}  {archive.name}\n", encoding="ascii")
        return BuildResult(output_dir, sysroot, archive, checksum, manifest)
    finally:
        if temporary is not None:
            temporary.cleanup()
