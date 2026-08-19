# Packaging Guide

This document describes how Linux distribution packages (.deb, .rpm, .pkg.tar.zst) are built and released for Kitty.

## Overview

Kitty provides automated package builds for:

| Format | Distributions | Architectures |
|--------|--------------|---------------|
| `.deb` | Debian, Ubuntu, Linux Mint, Pop!_OS | amd64, arm64, armhf |
| `.rpm` | Fedora, RHEL, CentOS, openSUSE | x86_64, aarch64, armv7hl |
| `.pkg.tar.zst` | Arch Linux, Manjaro, EndeavourOS | x86_64, aarch64, armv7h |

## Release Triggers

Packages are automatically built when:

1. **Tag push** - A git tag matching `v[0-9]+.[0-9]+.[0-9]+*` is pushed (e.g., `v1.0.0`, `v1.2.3-rc1`)
2. **Release publish** - A GitHub Release is published via the UI
3. **Manual dispatch** - Triggered manually via GitHub Actions UI (for testing)

## Where to Find Artifacts

After a successful build, all packages are uploaded to the corresponding **GitHub Release** page:

```
https://github.com/opentreecz/terminal-kitty/releases/tag/v<VERSION>
```

Each release includes:
- `kitty_<VERSION>_amd64.deb`
- `kitty_<VERSION>_arm64.deb`
- `kitty_<VERSION>_armhf.deb`
- `kitty-<VERSION>-1.<arch>.rpm`
- `kitty-<VERSION>-1-<arch>.pkg.tar.zst`
- `SHA256SUMS.txt` (checksums for all artifacts)

## Package Contents

All packages include:

- `/usr/bin/kitty` - Main terminal emulator binary
- `/usr/bin/kitten` - Kitten helper binary (Go-based sub-programs)
- `/usr/lib/kitty/` - Shared libraries and Python modules
- `/usr/share/applications/kitty.desktop` - Desktop entry
- `/usr/share/applications/kitty-open.desktop` - File opener entry
- `/usr/share/icons/hicolor/*/apps/kitty.png` - Application icons (multiple sizes)
- `/usr/share/icons/hicolor/scalable/apps/kitty.svg` - Scalable icon
- `/usr/share/man/man1/kitty.1` - Man page
- `/usr/share/man/man5/kitty.conf.5` - Configuration man page
- `/usr/share/terminfo/` - Terminfo entries (xterm-kitty)
- `/usr/share/doc/kitty/` - Documentation and HTML docs
- Shell integration scripts for bash, fish, zsh

## Build System

Kitty uses a custom `setup.py` build system (not setuptools). The primary build command is:

```bash
python3 setup.py linux-package --prefix /usr --update-check-interval=0
```

This produces a self-contained `linux-package/` directory that mirrors the final installation layout. The CI workflow repackages this into distribution-specific formats.

### Build Components
- **C code** - Terminal core, rendering (compiled with gcc)
- **Python** - Configuration, UI, kittens framework
- **Go** - Static binary kittens (`kitten` binary)
- **GLFW** - Vendored and customized window management

## Runtime Dependencies

| Debian/Ubuntu | Fedora/RHEL | Arch Linux |
|---------------|-------------|------------|
| python3 (>= 3.12) | python3 (>= 3.12) | python |
| libdbus-1-3 | dbus-libs | dbus |
| libfontconfig1 | fontconfig | fontconfig |
| libharfbuzz0b | harfbuzz | harfbuzz |
| libpng16-16 | libpng | libpng |
| libwayland-client0 | libwayland-client | wayland |
| libxkbcommon0 | libxkbcommon | libxkbcommon |
| liblcms2-2 | lcms2 | lcms2 |
| libgl1 | mesa-libGL | libgl |

## Building Packages Locally

### Prerequisites

- Python >= 3.12
- Go >= 1.22
- GCC
- Build dependencies for your distribution

### Build .deb locally

```bash
# Install dependencies (Debian/Ubuntu)
sudo apt-get install python3 python3-dev golang-go gcc pkg-config \
  libdbus-1-dev libxcursor-dev libxrandr-dev libxi-dev libxinerama-dev \
  libgl1-mesa-dev libfontconfig1-dev libharfbuzz-dev libx11-xcb-dev \
  libpng-dev libwayland-dev wayland-protocols libxkbcommon-dev \
  liblcms2-dev libxxhash-dev libsimde-dev

# Build
python3 setup.py linux-package --prefix /usr --update-check-interval=0

# Package (simplified)
VERSION=1.0.0
PKG_DIR="kitty_${VERSION}_amd64"
mkdir -p "${PKG_DIR}/DEBIAN"
cp -r linux-package/* "${PKG_DIR}/"
# Add DEBIAN/control (see .github/workflows/release-packages.yml)
dpkg-deb --build "${PKG_DIR}"
```

### Build .rpm locally

```bash
# Install dependencies (Fedora)
sudo dnf install python3 python3-devel golang gcc pkg-config \
  dbus-devel libXcursor-devel libXrandr-devel libXi-devel \
  libXinerama-devel mesa-libGL-devel fontconfig-devel harfbuzz-devel \
  libxcb-devel libpng-devel wayland-devel wayland-protocols-devel \
  libxkbcommon-devel lcms2-devel xxhash-devel simde-devel rpm-build

# Build
python3 setup.py linux-package --prefix /usr --update-check-interval=0

# Package
rpmbuild -bb packaging/rpm/kitty.spec
```

### Build Arch package locally

```bash
# Install dependencies
sudo pacman -S python go gcc pkg-config dbus fontconfig freetype2 \
  harfbuzz libpng wayland wayland-protocols libxkbcommon lcms2 \
  libgl libxi libxrandr libxcursor libxinerama xxhash simde

# Build with makepkg
cd packaging/arch
makepkg -sf
```

## Testing the Workflow

To test the release workflow without creating a real release:

1. Go to **Actions** > **Release Linux Packages**
2. Click **Run workflow**
3. Enter a version number (e.g., `0.0.1-test`)
4. Click **Run workflow**

Artifacts will be available for download from the workflow run (not attached to a release).

## Dependabot

This project uses [Dependabot](https://docs.github.com/en/code-security/dependabot) to keep dependencies up to date:

- **Go modules** - Checked weekly (Mondays), grouped into a single PR
- **GitHub Actions** - Checked weekly (Mondays), grouped into a single PR
- **pip (Python)** - Checked weekly (Mondays), grouped into a single PR

All ecosystems have a 7-day cooldown to prevent excessive PR creation.

### Reviewing Dependabot PRs

1. Check the PR description for changelog/compatibility notes
2. Ensure CI passes (the existing CI workflow runs full test matrix including ASAN)
3. For Go module updates, verify no breaking API changes
4. For Python updates, ensure build system compatibility
5. Merge if all checks pass

## Troubleshooting

### Common Build Failures

| Issue | Solution |
|-------|----------|
| Python version too old | Kitty requires Python >= 3.12 |
| Go version too old | Kitty requires Go >= 1.22 |
| Missing Wayland protocols | Install `wayland-protocols` package |
| Missing SIMDE headers | Install `libsimde-dev` (Debian) or `simde-devel` (Fedora) |
| QEMU timeout on arm | ARM builds under emulation are slow; increase timeout |
| setup.py compilation error | Check that all `-dev`/`-devel` packages are installed |

### Architecture Notes

- **amd64/x86_64**: Native build, fastest (~5 minutes)
- **arm64/aarch64**: Built in arm64 Docker container under QEMU (~15-30 minutes)
- **armhf/armv7h**: Built in arm32 Docker container under QEMU (~20-40 minutes)

The multi-language nature of Kitty (C + Python + Go) makes cross-compilation complex, so native builds in architecture-specific containers via QEMU are used instead.

## Packaging File Locations

```
packaging/
├── arch/
│   └── PKGBUILD          # Arch Linux package definition
├── debian/
│   ├── compat            # Debhelper compatibility level
│   ├── control           # Package metadata and dependencies
│   ├── copyright         # License information (GPL-3.0)
│   └── rules             # Build rules
└── rpm/
    └── kitty.spec        # RPM specification file
```

## Related Build Systems

- **bypy/**: Cross-platform binary packaging (used for official releases)
- **setup.py**: Custom build system handling C compilation, Go builds, Python packaging
- **Makefile**: Delegates to `python3 setup.py` for most targets

## Workflow File

The main workflow file is located at:
```
.github/workflows/release-packages.yml
```
