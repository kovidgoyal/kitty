{ pkgs ? import <nixpkgs> { } }:
with pkgs;

let
  inherit (lib) optional optionals;
  inherit (xorg) libX11 libXrandr libXinerama libXcursor libXi libXext;
  inherit (darwin.apple_sdk.frameworks) Cocoa CoreGraphics Foundation IOKit Kernel OpenGL;
  harfbuzzWithCoreText = harfbuzz.override { withCoreText = stdenv.isDarwin; };
in
mkShell rec {
  buildInputs = [
    harfbuzzWithCoreText
    ncurses
    lcms2
  ] ++ optionals stdenv.isDarwin [
    Cocoa
    CoreGraphics
    Foundation
    IOKit
    Kernel
    OpenGL
    libpng
    python3
    zlib
  ] ++ optionals stdenv.isLinux [
    fontconfig libunistring libcanberra libX11
    libXrandr libXinerama libXcursor libxkbcommon libXi libXext
    wayland-protocols wayland dbus
  ] ++ checkInputs;

  nativeBuildInputs = [
    pkgconfig python3Packages.sphinx ncurses
  ] ++ optionals stdenv.isDarwin [
    imagemagick
    libicns  # For the png2icns tool.
    installShellFiles
  ];

  propagatedBuildInputs = optional stdenv.isLinux libGL;

  checkInputs = [
    python3Packages.pillow
  ];

  # Causes build failure due to warning when using Clang
  hardeningDisable = [ "strictoverflow" ];

  shellHook = if stdenv.isDarwin then ''
    export KITTY_NO_LTO=
  '' else ''
    export KITTY_EGL_LIBRARY='${stdenv.lib.getLib libGL}/lib/libEGL.so.1'
    export KITTY_STARTUP_NOTIFICATION_LIBRARY='${libstartup_notification}/lib/libstartup-notification-1.so'
    export KITTY_CANBERRA_LIBRARY='${libcanberra}/lib/libcanberra.so'
  '';
}
