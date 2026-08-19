Name:           kitty
Version:        %{version}
Release:        1%{?dist}
Summary:        The fast, feature-rich, GPU based terminal emulator
License:        GPL-3.0-only
URL:            https://sw.kovidgoyal.net/kitty/
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3 >= 3.12
BuildRequires:  python3-devel
BuildRequires:  golang >= 1.22
BuildRequires:  gcc
BuildRequires:  pkg-config
BuildRequires:  dbus-devel
BuildRequires:  libXcursor-devel
BuildRequires:  libXrandr-devel
BuildRequires:  libXi-devel
BuildRequires:  libXinerama-devel
BuildRequires:  mesa-libGL-devel
BuildRequires:  fontconfig-devel
BuildRequires:  harfbuzz-devel
BuildRequires:  libxcb-devel
BuildRequires:  libpng-devel
BuildRequires:  wayland-devel
BuildRequires:  wayland-protocols-devel
BuildRequires:  libxkbcommon-devel
BuildRequires:  lcms2-devel
BuildRequires:  xxhash-devel
BuildRequires:  simde-devel

Requires:       python3 >= 3.12
Requires:       dbus-libs
Requires:       fontconfig
Requires:       harfbuzz
Requires:       libpng
Requires:       libwayland-client
Requires:       libxkbcommon
Requires:       lcms2

%description
kitty is a free and open-source GPU-accelerated terminal emulator for Linux
and macOS focused on performance and features. kitty is written in a mix of
C and Python, with the Go programming language used for its "kittens"
(sub-programs that extend its functionality).

%prep
%autosetup -n %{name}-%{version}

%build
python3 setup.py linux-package --prefix /usr --update-check-interval=0

%install
mkdir -p %{buildroot}
cp -r linux-package/* %{buildroot}/

%files
%license LICENSE
%doc README.asciidoc CHANGELOG.rst
%{_bindir}/kitty
%{_bindir}/kitten
%{_libdir}/kitty/
%{_datadir}/applications/kitty.desktop
%{_datadir}/applications/kitty-open.desktop
%{_datadir}/icons/hicolor/*/apps/kitty.png
%{_datadir}/icons/hicolor/scalable/apps/kitty.svg
%{_datadir}/man/man1/kitty.1*
%{_datadir}/man/man5/kitty.conf.5*
%{_datadir}/terminfo/
%{_datadir}/doc/kitty/
%{_sysconfdir}/xdg/kitty/

%changelog
* Mon Jan 01 2024 Kitty Maintainers <maintainers@sw.kovidgoyal.net> - %{version}-1
- Initial RPM package build via GitHub Actions
