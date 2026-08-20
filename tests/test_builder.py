import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from cm0_bsp_builder.builder import (
    BuildError,
    Profile,
    create_archive,
    export_sysroot,
    load_profile,
    parse_dpkg_status,
    validate_sysroot,
)


class BuilderTests(unittest.TestCase):
    def test_factory_profile_loads(self):
        profile = load_profile("factory-test")
        self.assertEqual(profile.name, "factory-test")
        self.assertIn("libdrm-dev", profile.development_packages)
        self.assertIn("usr/include/xf86drm.h", profile.required_paths)

    def test_base_profile_includes_display_development_files(self):
        profile = load_profile("base")
        self.assertEqual(profile.name, "base")
        self.assertIn("libdrm-dev", profile.development_packages)
        self.assertIn("libpciaccess-dev", profile.development_packages)
        self.assertIn("libwayland-dev", profile.development_packages)
        self.assertIn("libxkbcommon-dev", profile.development_packages)
        self.assertIn("libffi-dev", profile.development_packages)
        self.assertIn("usr/include/stdio.h", profile.required_paths)
        self.assertIn("usr/include/xf86drm.h", profile.required_paths)
        self.assertIn("usr/include/pciaccess.h", profile.required_paths)
        self.assertIn("usr/include/wayland-client.h", profile.required_paths)
        self.assertIn("usr/include/xkbcommon/xkbcommon.h", profile.required_paths)
        self.assertIn("usr/include/aarch64-linux-gnu/ffi.h", profile.required_paths)

    def test_profile_rejects_parent_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "bad",
                        "description": "bad",
                        "development_packages": [],
                        "export_paths": ["../etc"],
                        "required_paths": [],
                    }
                )
            )
            with self.assertRaises(BuildError):
                load_profile(str(path))

    def test_export_preserves_symlinks_and_validation(self):
        profile = Profile(
            "test",
            "test",
            (),
            ("usr/include", "lib/link", "lib/target.so"),
            ("usr/include/a.h", "lib/link"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            sysroot = Path(temporary) / "sysroot"
            (root / "usr/include").mkdir(parents=True)
            (root / "usr/include/a.h").write_text("header")
            (root / "lib").mkdir()
            (root / "lib/link").symlink_to("target.so")
            (root / "lib/target.so").write_text("library")

            export_sysroot(root, sysroot, profile)
            self.assertEqual((sysroot / "usr/include/a.h").read_text(), "header")
            self.assertTrue((sysroot / "lib/link").is_symlink())
            self.assertEqual(validate_sysroot(sysroot, profile), [])

    def test_validation_rejects_broken_symlink(self):
        profile = Profile("test", "test", (), (), ("usr/include/required.h",))
        with tempfile.TemporaryDirectory() as temporary:
            sysroot = Path(temporary) / "sysroot"
            (sysroot / "usr/include").mkdir(parents=True)
            (sysroot / "usr/include/required.h").symlink_to("missing.h")

            self.assertEqual(
                validate_sysroot(sysroot, profile), ["usr/include/required.h"]
            )

    def test_parse_dpkg_status(self):
        contents = """Package: libc6
Status: install ok installed
Architecture: arm64
Version: 2.41

Package: removed
Status: deinstall ok config-files
Architecture: arm64
Version: 1
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status"
            path.write_text(contents)
            self.assertEqual(
                parse_dpkg_status(path),
                [{"package": "libc6", "version": "2.41", "architecture": "arm64"}],
            )

    def test_archive_has_stable_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sysroot"
            root.mkdir()
            file_path = root / "usr/include/test.h"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("test")
            os.utime(file_path, (123456789, 123456789))
            first = Path(temporary) / "one.tar.gz"
            second = Path(temporary) / "two.tar.gz"
            create_archive(root, first)
            create_archive(root, second)
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest(),
            )


if __name__ == "__main__":
    unittest.main()
