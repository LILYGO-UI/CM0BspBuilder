from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from .builder import BuildError


TOOLCHAIN_RESOURCE = "resources/cm0-aarch64-linux-gnu.cmake"
TOOLCHAIN_RELATIVE_PATH = "usr/share/cm0-bsp/toolchain.cmake"


def toolchain_text() -> str:
    return (
        resources.files("cm0_bsp_builder")
        .joinpath(TOOLCHAIN_RESOURCE)
        .read_text(encoding="utf-8")
    )


def install_toolchain(sysroot: Path) -> Path:
    sysroot = sysroot.expanduser().resolve()
    destination = sysroot / TOOLCHAIN_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(toolchain_text(), encoding="utf-8")
    return destination


def resolve_sdk_root(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    roots = (candidate, candidate / "sysroot")
    for root in roots:
        if (root / "usr/include").is_dir() and (root / "usr/lib").is_dir():
            return root
    raise BuildError(
        f"CM0 BSP sysroot not found below {candidate}; expected usr/include and usr/lib"
    )


def initialize_cmake_project(project_dir: Path, sdk_path: Path) -> Path:
    project_dir = project_dir.expanduser().resolve()
    if not (project_dir / "CMakeLists.txt").is_file():
        raise BuildError(f"CMakeLists.txt not found in project directory: {project_dir}")

    sdk_root = resolve_sdk_root(sdk_path)
    toolchain = sdk_root / TOOLCHAIN_RELATIVE_PATH
    if not toolchain.is_file():
        raise BuildError(
            f"BSP does not contain {TOOLCHAIN_RELATIVE_PATH}; rebuild it with this "
            "CM0BspBuilder version"
        )

    destination = project_dir / "CMakeUserPresets.json"
    if destination.exists():
        raise BuildError(f"refusing to overwrite existing file: {destination}")

    data = {
        "version": 3,
        "configurePresets": [
            {
                "name": "cm0-cross",
                "displayName": "CM0 AArch64 cross build",
                "binaryDir": "${sourceDir}/build/cm0-cross",
                "cacheVariables": {
                    "CMAKE_TOOLCHAIN_FILE": str(toolchain),
                    "CM0_SDK_ROOT": str(sdk_root),
                    "CMAKE_BUILD_TYPE": "Release",
                },
            }
        ],
        "buildPresets": [
            {"name": "cm0-cross", "configurePreset": "cm0-cross"}
        ],
    }
    destination.write_text(
        json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    return destination
