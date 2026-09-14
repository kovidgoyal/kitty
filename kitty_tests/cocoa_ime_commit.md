# Cocoa IME commit regression

This standalone macOS test calls the actual `GLFWContentView` methods from a
specified `glfw-cocoa.so`. It does not start an input method or open a window.
After building from source, run it through the normal test entry point:

```sh
./test.py macos_ime_commit
```

The runner skips this test outside macOS or if `clang` is unavailable. It also
links the probe with the sanitizer runtime when the Cocoa module uses ASan.
For a standalone run against an unsanitized module from a matching checkout:

```sh
mkdir -p build/ime-test
clang -D_GLFW_COCOA -fno-objc-arc -framework Cocoa -framework Carbon \
    kitty_tests/cocoa_ime_commit.m -o build/ime-test/cocoa_ime_commit
build/ime-test/cocoa_ime_commit "$PWD/kitty/glfw-cocoa.so"
```

The test covers UTF-8 length boundaries, long Chinese and emoji commits,
attributed strings with combining characters and embedded newlines,
preedit clearing, separate callbacks, and existing control/empty input handling.
It also checks that key-handler callbacks continue staging text and that the
modifier branch retains its previous behavior, including its existing limit.
The change under test only removes the limit on event-loop commits.

The fixture allocates the native receiver without initializing NSView/window
lifecycle, and supplies only the ivars and keyboard callback used by the tested
methods. These small fixture objects deliberately live until process exit;
NSView destruction is not invoked on the uninitialized view. No NSApplication,
NSWindow, input context, Accessibility action or synthetic GUI event is created.

Callback mode fixtures test staging within `insertText`, not a complete physical
keyDown/flagsChanged sequence. Delivery is observed at the native GLFW callback,
not at a terminal child or editor. Run each native module in a separate process
to avoid Objective-C class-name collisions. Against the pre-fix module this test
must fail the oversized event-loop cases; against the repaired module it must
report `all_passed: true` and exit zero.
