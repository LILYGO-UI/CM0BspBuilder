import json
import tempfile
import unittest
from pathlib import Path

from cm0_bsp_builder.builder import BuildError
from cm0_bsp_builder.project import (
    TOOLCHAIN_RELATIVE_PATH,
    initialize_cmake_project,
    install_toolchain,
    resolve_sdk_root,
)


class ProjectTests(unittest.TestCase):
    def make_sysroot(self, root: Path) -> Path:
        sysroot = root / "sysroot"
        (sysroot / "usr/include").mkdir(parents=True)
        (sysroot / "usr/lib").mkdir()
        return sysroot

    def test_install_toolchain_and_resolve_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sdk"
            sysroot = self.make_sysroot(output)
            toolchain = install_toolchain(sysroot)

            self.assertEqual(toolchain, sysroot.resolve() / TOOLCHAIN_RELATIVE_PATH)
            self.assertIn("CM0_SDK_ROOT", toolchain.read_text())
            self.assertEqual(resolve_sdk_root(output), sysroot.resolve())

    def test_initialize_cmake_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "application"
            project.mkdir()
            (project / "CMakeLists.txt").write_text("project(test)\n")
            sysroot = self.make_sysroot(root / "sdk")
            toolchain = install_toolchain(sysroot)

            destination = initialize_cmake_project(project, sysroot)
            data = json.loads(destination.read_text())
            preset = data["configurePresets"][0]
            self.assertEqual(preset["name"], "cm0-cross")
            self.assertEqual(
                preset["cacheVariables"]["CMAKE_TOOLCHAIN_FILE"], str(toolchain)
            )
            self.assertEqual(
                preset["cacheVariables"]["CM0_SDK_ROOT"], str(sysroot.resolve())
            )

            with self.assertRaises(BuildError):
                initialize_cmake_project(project, sysroot)


if __name__ == "__main__":
    unittest.main()
