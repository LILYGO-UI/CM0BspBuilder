# CM0 BSP Builder

`CM0BspBuilder` is a standalone SDK production project. It creates a reusable
AArch64 application sysroot from a released Raspberry Pi OS ZIP or raw IMG.
Application repositories consume the generated BSP; they do not need to copy
the builder source or depend on FactoryTest.

The input image is opened read-only and is never mounted or modified. The
result is suitable for CMake, GCC `--sysroot`, and pkg-config. It is not a
bootloader, kernel, device-tree, or kernel-module BSP.

## Project boundary

The builder owns:

- image inspection and read-only root filesystem extraction;
- reusable and application-specific sysroot profiles;
- target development-package overlays;
- the CM0 AArch64 CMake toolchain;
- versioned BSP archives, checksums, and manifests.

Application projects own their source, build options, packaging, and runtime
deployment. A generated BSP is the interface between the two projects.

## Host setup

Linux:

```sh
sudo apt-get install python3 e2fsprogs dpkg
```

macOS:

```sh
brew install e2fsprogs dpkg
```

Install the CLI in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
cm0-bsp doctor
```

For a zero-install invocation from this checkout, use `./cm0-bsp`. The Python
package has no runtime dependencies. A complete build needs roughly 25 GiB of
temporary free space for the current production image.

## Build a reusable BSP

The default `base` profile contains the C/C++ runtime, libc headers, Linux UAPI
headers, startup objects, DRM development files, and pkg-config search roots
needed by normal applications:

```sh
cm0-bsp inspect /path/to/raspios.zip
cm0-bsp build /path/to/raspios.zip \
  --deb-dir packages/arm64-debs \
  --output dist/2026-07-30-base
```

The output directory must be empty. Generated files are:

```text
dist/2026-07-30-base/
├── sysroot/
│   ├── etc/
│   ├── lib/
│   ├── usr/
│   │   └── share/cm0-bsp/
│   │       ├── manifest.json
│   │       └── toolchain.cmake
│   └── var/lib/dpkg/status
├── sdk_bsp.tar.gz
└── sdk_bsp.tar.gz.sha256
```

The archive extracts directly as a sysroot. The manifest records the source
image hash, partition table, OS release, installed packages, selected profile,
validation result, and overlaid `.deb` hashes.

Use an external disk for temporary data when necessary:

```sh
cm0-bsp build IMAGE.zip \
  --work-dir /Volumes/work/cm0-bsp-work \
  --output dist/cm0-bsp
```

`--allow-incomplete` is only for image diagnostics. Do not publish or use such
an archive for application builds.

## Application profiles

Use a profile when an application requires libraries beyond the base C/C++
SDK. The included `factory-test` profile is one example:

```sh
cm0-bsp requirements --profile factory-test
cm0-bsp build IMAGE.zip \
  --profile factory-test \
  --deb-dir /path/to/arm64-debs \
  --output dist/2026-07-30-factory-test
```

Development packages must come from the same Raspberry Pi OS release and
repositories as the source image. A custom JSON profile can be passed directly
with `--profile /path/to/application.json`; it uses the same schema as the
profiles under `src/cm0_bsp_builder/profiles`.

## Use from another CMake project

Install a host cross compiler first:

```sh
# Apple Silicon macOS
brew install cmake pkg-config aarch64-unknown-linux-gnu

# Debian/Ubuntu
sudo apt-get install cmake pkg-config gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
```

The generated toolchain is self-locating. Point CMake at the extracted sysroot:

```sh
cmake -S . -B build/cm0 \
  -DCMAKE_TOOLCHAIN_FILE=/opt/cm0-sdk/usr/share/cm0-bsp/toolchain.cmake \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build/cm0 --parallel
```

Alternatively, initialize presets in an existing CMake application. The
command accepts either the builder output directory or the sysroot itself and
refuses to overwrite an existing `CMakeUserPresets.json`:

```sh
cm0-bsp init /path/to/application --sdk dist/2026-07-30-base
cd /path/to/application
cmake --preset cm0-cross
cmake --build --preset cm0-cross --parallel
```

For CI, the same toolchain also accepts `CM0_SDK_ROOT` as a CMake cache value
or environment variable. Rebuild and republish the BSP whenever the production
image changes glibc, the OS release, or any linked target library.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
