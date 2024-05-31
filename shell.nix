{pkgs ? import <nixpkgs> {}}:
with pkgs; let
  inherit (lib) optional optionals;
  inherit (xorg) libX11 libXrandr libXinerama libXcursor libXi libXext;
  inherit (darwin.apple_sdk.frameworks) Cocoa CoreGraphics Foundation IOKit Kernel OpenGL UniformTypeIdentifiers;
  harfbuzzWithCoreText = harfbuzz.override {withCoreText = stdenv.isDarwin;};
in
  with python3Packages;
    mkShell rec {
      buildInputs =
        [
          harfbuzzWithCoreText
          ncurses
          lcms2
          xxhash
        ]
        ++ optionals stdenv.isDarwin [
          Cocoa
          CoreGraphics
          Foundation
          IOKit
          Kernel
          OpenGL
          UniformTypeIdentifiers
          libpng
          python3
          zlib
        ]
        ++ lib.optionals (stdenv.isDarwin && (builtins.hasAttr "UserNotifications" darwin.apple_sdk.frameworks)) [
          darwin.apple_sdk.frameworks.UserNotifications
        ]
        ++ optionals stdenv.isLinux [
          fontconfig
          libunistring
          libcanberra
          libX11
          libXrandr
          libXinerama
          libXcursor
          libxkbcommon
          libXi
          libXext
          wayland-protocols
          wayland
          openssl
          xxHash
          dbus
          simde
        ]
        ++ checkInputs;

      nativeBuildInputs =
        [
          ncurses
          pkg-config
          sphinx
          furo
          sphinx-copybutton
          sphinxext-opengraph
          sphinx-inline-tabs
        ]
        ++ optionals stdenv.isDarwin [
          imagemagick
          libicns # For the png2icns tool.
        ];

      propagatedBuildInputs = optional stdenv.isLinux libGL;

      checkInputs = [
        pillow
      ];

      # Causes build failure due to warning when using Clang
      hardeningDisable = ["strictoverflow"];

      shellHook =
        if stdenv.isDarwin
        then ''
          export KITTY_NO_LTO=
        ''
        else ''
          export KITTY_EGL_LIBRARY='${lib.getLib libGL}/lib/libEGL.so.1'
          export KITTY_STARTUP_NOTIFICATION_LIBRARY='${libstartup_notification}/lib/libstartup-notification-1.so'
          export KITTY_CANBERRA_LIBRARY='${libcanberra}/lib/libcanberra.so'
        '';
    }
