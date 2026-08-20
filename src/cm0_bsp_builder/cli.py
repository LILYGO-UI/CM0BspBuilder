from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .builder import (
    BuildError,
    build_bsp,
    find_debugfs,
    inspect_source,
    load_profile,
)
from .image import ImageError
from .project import initialize_cmake_project


def _size(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} TiB"


def command_inspect(args: argparse.Namespace) -> int:
    source, partitions, root = inspect_source(args.image)
    data = {
        "source": str(source.path),
        "container": "zip" if source.compressed else "raw",
        "image_name": source.image_name,
        "image_size": source.image_size,
        "partitions": [item.to_dict() for item in partitions],
        "selected_root_partition": root.to_dict(),
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"Source: {source.path}")
    print(f"Container: {data['container']}")
    print(f"Image: {source.image_name} ({_size(source.image_size)})")
    print("Partitions:")
    for item in partitions:
        selected = " [rootfs]" if item == root else ""
        label = f" {item.name}" if item.name else ""
        print(
            f"  {item.index}: {item.scheme} {item.type_code}{label}, "
            f"start={item.start_lba}, size={_size(item.size_bytes)}{selected}"
        )
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    print(f"cm0-bsp-builder: {__version__}")
    print(f"Python: {sys.version.split()[0]}")
    try:
        print(f"debugfs: {find_debugfs(args.debugfs)}")
    except BuildError as error:
        print(f"debugfs: unavailable ({error})")
    dpkg_deb = shutil.which("dpkg-deb")
    print(f"dpkg-deb: {dpkg_deb or 'unavailable (needed only for --deb-dir)'}")
    return 0


def command_requirements(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    if args.shell:
        print(" ".join(profile.development_packages))
    else:
        print(f"Profile: {profile.name}")
        print(profile.description)
        print("Development packages:")
        for package in profile.development_packages:
            print(f"  {package}")
    return 0


def command_init(args: argparse.Namespace) -> int:
    destination = initialize_cmake_project(Path(args.project), Path(args.sdk))
    print(f"Created: {destination}")
    print("Configure: cmake --preset cm0-cross")
    print("Build: cmake --build --preset cm0-cross")
    return 0


def command_build(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    result = build_bsp(
        Path(args.image),
        Path(args.output),
        profile,
        debugfs_path=args.debugfs,
        deb_dir=Path(args.deb_dir) if args.deb_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        keep_work=args.keep_work,
        allow_incomplete=args.allow_incomplete,
        progress=lambda message: print(f"==> {message}", flush=True),
    )
    print(f"Sysroot: {result.sysroot_dir}")
    print(f"Archive: {result.archive}")
    print(f"Checksum: {result.checksum}")
    print(f"Manifest: {result.manifest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cm0-bsp",
        description="Create an AArch64 application sysroot from a Raspberry Pi OS image",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="inspect the ZIP/IMG and select its Linux root partition"
    )
    inspect_parser.add_argument("image")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(handler=command_inspect)

    doctor_parser = subparsers.add_parser(
        "doctor", help="check host tools without changing the system"
    )
    doctor_parser.add_argument("--debugfs")
    doctor_parser.set_defaults(handler=command_doctor)

    requirements_parser = subparsers.add_parser(
        "requirements", help="list development packages required by a profile"
    )
    requirements_parser.add_argument("--profile", default="base")
    requirements_parser.add_argument("--shell", action="store_true")
    requirements_parser.set_defaults(handler=command_requirements)

    build_parser = subparsers.add_parser(
        "build", help="extract the rootfs and build sdk_bsp.tar.gz"
    )
    build_parser.add_argument("image")
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--profile", default="base")
    build_parser.add_argument("--debugfs")
    build_parser.add_argument(
        "--deb-dir", help="directory of target arm64 development .deb packages to overlay"
    )
    build_parser.add_argument("--work-dir")
    build_parser.add_argument("--keep-work", action="store_true")
    build_parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="package even when profile files are missing",
    )
    build_parser.set_defaults(handler=command_build)

    init_parser = subparsers.add_parser(
        "init", help="configure a CMake application to use an extracted BSP"
    )
    init_parser.add_argument(
        "project", nargs="?", default=".", help="CMake project directory (default: .)"
    )
    init_parser.add_argument(
        "--sdk", required=True, help="BSP output directory or extracted sysroot"
    )
    init_parser.set_defaults(handler=command_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (BuildError, ImageError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
