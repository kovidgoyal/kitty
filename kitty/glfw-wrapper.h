#pragma once
#include <stddef.h>
#include <stdint.h>



/*! @name GLFW version macros
 *  @{ */
/*! @brief The major version number of the GLFW library.
 *
 *  This is incremented when the API is changed in non-compatible ways.
 *  @ingroup init
 */
#define GLFW_VERSION_MAJOR          3
/*! @brief The minor version number of the GLFW library.
 *
 *  This is incremented when features are added to the API but it remains
 *  backward-compatible.
 *  @ingroup init
 */
#define GLFW_VERSION_MINOR          3
/*! @brief The revision number of the GLFW library.
 *
 *  This is incremented when a bug fix release is made that does not contain any
 *  API changes.
 *  @ingroup init
 */
#define GLFW_VERSION_REVISION       0
/*! @} */

/*! @name Boolean values
 *  @{ */
/*! @brief One.
 *
 *  One.  Seriously.  You don't _need_ to use this symbol in your code.  It's
 *  semantic sugar for the number 1.  You can also use `1` or `true` or `_True`
 *  or `GL_TRUE` or whatever you want.
 */
#define GLFW_TRUE                   true
/*! @brief Zero.
 *
 *  Zero.  Seriously.  You don't _need_ to use this symbol in your code.  It's
 *  semantic sugar for the number 0.  You can also use `0` or `false` or
 *  `_False` or `GL_FALSE` or whatever you want.
 */
#define GLFW_FALSE                  false
/*! @} */

/*! @name Key and button actions
 *  @{ */
/*! @brief The key or mouse button was released.
 *
 *  The key or mouse button was released.
 *
 *  @ingroup input
 */
#define GLFW_RELEASE                0
/*! @brief The key or mouse button was pressed.
 *
 *  The key or mouse button was pressed.
 *
 *  @ingroup input
 */
#define GLFW_PRESS                  1
/*! @brief The key was held down until it repeated.
 *
 *  The key was held down until it repeated.
 *
 *  @ingroup input
 */
#define GLFW_REPEAT                 2
/*! @} */

/*! @defgroup hat_state Joystick hat states
 *
 *  See [joystick hat input](@ref joystick_hat) for how these are used.
 *
 *  @ingroup input
 *  @{ */
#define GLFW_HAT_CENTERED           0
#define GLFW_HAT_UP                 1
#define GLFW_HAT_RIGHT              2
#define GLFW_HAT_DOWN               4
#define GLFW_HAT_LEFT               8
#define GLFW_HAT_RIGHT_UP           (GLFW_HAT_RIGHT | GLFW_HAT_UP)
#define GLFW_HAT_RIGHT_DOWN         (GLFW_HAT_RIGHT | GLFW_HAT_DOWN)
#define GLFW_HAT_LEFT_UP            (GLFW_HAT_LEFT  | GLFW_HAT_UP)
#define GLFW_HAT_LEFT_DOWN          (GLFW_HAT_LEFT  | GLFW_HAT_DOWN)
/*! @} */

/*! @defgroup keys Keyboard keys
 *  @brief Keyboard key IDs.
 *
 *  See [key input](@ref input_key) for how these are used.
 *
 *  These key codes are inspired by the _USB HID Usage Tables v1.12_ (p. 53-60),
 *  but re-arranged to map to 7-bit ASCII for printable keys (function keys are
 *  put in the 256+ range).
 *
 *  The naming of the key codes follow these rules:
 *   - The US keyboard layout is used
 *   - Names of printable alpha-numeric characters are used (e.g. "A", "R",
 *     "3", etc.)
 *   - For non-alphanumeric characters, Unicode:ish names are used (e.g.
 *     "COMMA", "LEFT_SQUARE_BRACKET", etc.). Note that some names do not
 *     correspond to the Unicode standard (usually for brevity)
 *   - Keys that lack a clear US mapping are named "WORLD_x"
 *   - For non-printable keys, custom names are used (e.g. "F4",
 *     "BACKSPACE", etc.)
 *
 *  @ingroup input
 *  @{
 */

/* The unknown key */
#define GLFW_KEY_UNKNOWN            -1

/* Printable keys */
#define GLFW_KEY_SPACE              32
#define GLFW_KEY_APOSTROPHE         39  /* ' */
#define GLFW_KEY_COMMA              44  /* , */
#define GLFW_KEY_MINUS              45  /* - */
#define GLFW_KEY_PERIOD             46  /* . */
#define GLFW_KEY_SLASH              47  /* / */
#define GLFW_KEY_0                  48
#define GLFW_KEY_1                  49
#define GLFW_KEY_2                  50
#define GLFW_KEY_3                  51
#define GLFW_KEY_4                  52
#define GLFW_KEY_5                  53
#define GLFW_KEY_6                  54
#define GLFW_KEY_7                  55
#define GLFW_KEY_8                  56
#define GLFW_KEY_9                  57
#define GLFW_KEY_SEMICOLON          59  /* ; */
#define GLFW_KEY_EQUAL              61  /* = */
#define GLFW_KEY_A                  65
#define GLFW_KEY_B                  66
#define GLFW_KEY_C                  67
#define GLFW_KEY_D                  68
#define GLFW_KEY_E                  69
#define GLFW_KEY_F                  70
#define GLFW_KEY_G                  71
#define GLFW_KEY_H                  72
#define GLFW_KEY_I                  73
#define GLFW_KEY_J                  74
#define GLFW_KEY_K                  75
#define GLFW_KEY_L                  76
#define GLFW_KEY_M                  77
#define GLFW_KEY_N                  78
#define GLFW_KEY_O                  79
#define GLFW_KEY_P                  80
#define GLFW_KEY_Q                  81
#define GLFW_KEY_R                  82
#define GLFW_KEY_S                  83
#define GLFW_KEY_T                  84
#define GLFW_KEY_U                  85
#define GLFW_KEY_V                  86
#define GLFW_KEY_W                  87
#define GLFW_KEY_X                  88
#define GLFW_KEY_Y                  89
#define GLFW_KEY_Z                  90
#define GLFW_KEY_LEFT_BRACKET       91  /* [ */
#define GLFW_KEY_BACKSLASH          92  /* \ */
#define GLFW_KEY_RIGHT_BRACKET      93  /* ] */
#define GLFW_KEY_GRAVE_ACCENT       96  /* ` */
#define GLFW_KEY_WORLD_1            161 /* non-US #1 */
#define GLFW_KEY_WORLD_2            162 /* non-US #2 */
#define GLFW_KEY_PLUS               163

/* Function keys */
#define GLFW_KEY_ESCAPE             256
#define GLFW_KEY_ENTER              257
#define GLFW_KEY_TAB                258
#define GLFW_KEY_BACKSPACE          259
#define GLFW_KEY_INSERT             260
#define GLFW_KEY_DELETE             261
#define GLFW_KEY_RIGHT              262
#define GLFW_KEY_LEFT               263
#define GLFW_KEY_DOWN               264
#define GLFW_KEY_UP                 265
#define GLFW_KEY_PAGE_UP            266
#define GLFW_KEY_PAGE_DOWN          267
#define GLFW_KEY_HOME               268
#define GLFW_KEY_END                269
#define GLFW_KEY_CAPS_LOCK          280
#define GLFW_KEY_SCROLL_LOCK        281
#define GLFW_KEY_NUM_LOCK           282
#define GLFW_KEY_PRINT_SCREEN       283
#define GLFW_KEY_PAUSE              284
#define GLFW_KEY_F1                 290
#define GLFW_KEY_F2                 291
#define GLFW_KEY_F3                 292
#define GLFW_KEY_F4                 293
#define GLFW_KEY_F5                 294
#define GLFW_KEY_F6                 295
#define GLFW_KEY_F7                 296
#define GLFW_KEY_F8                 297
#define GLFW_KEY_F9                 298
#define GLFW_KEY_F10                299
#define GLFW_KEY_F11                300
#define GLFW_KEY_F12                301
#define GLFW_KEY_F13                302
#define GLFW_KEY_F14                303
#define GLFW_KEY_F15                304
#define GLFW_KEY_F16                305
#define GLFW_KEY_F17                306
#define GLFW_KEY_F18                307
#define GLFW_KEY_F19                308
#define GLFW_KEY_F20                309
#define GLFW_KEY_F21                310
#define GLFW_KEY_F22                311
#define GLFW_KEY_F23                312
#define GLFW_KEY_F24                313
#define GLFW_KEY_F25                314
#define GLFW_KEY_KP_0               320
#define GLFW_KEY_KP_1               321
#define GLFW_KEY_KP_2               322
#define GLFW_KEY_KP_3               323
#define GLFW_KEY_KP_4               324
#define GLFW_KEY_KP_5               325
#define GLFW_KEY_KP_6               326
#define GLFW_KEY_KP_7               327
#define GLFW_KEY_KP_8               328
#define GLFW_KEY_KP_9               329
#define GLFW_KEY_KP_DECIMAL         330
#define GLFW_KEY_KP_DIVIDE          331
#define GLFW_KEY_KP_MULTIPLY        332
#define GLFW_KEY_KP_SUBTRACT        333
#define GLFW_KEY_KP_ADD             334
#define GLFW_KEY_KP_ENTER           335
#define GLFW_KEY_KP_EQUAL           336
#define GLFW_KEY_LEFT_SHIFT         340
#define GLFW_KEY_LEFT_CONTROL       341
#define GLFW_KEY_LEFT_ALT           342
#define GLFW_KEY_LEFT_SUPER         343
#define GLFW_KEY_RIGHT_SHIFT        344
#define GLFW_KEY_RIGHT_CONTROL      345
#define GLFW_KEY_RIGHT_ALT          346
#define GLFW_KEY_RIGHT_SUPER        347
#define GLFW_KEY_MENU               348

#define GLFW_KEY_LAST               GLFW_KEY_MENU

/*! @} */

/*! @defgroup mods Modifier key flags
 *  @brief Modifier key flags.
 *
 *  See [key input](@ref input_key) for how these are used.
 *
 *  @ingroup input
 *  @{ */

/*! @brief If this bit is set one or more Shift keys were held down.
 *
 *  If this bit is set one or more Shift keys were held down.
 */
#define GLFW_MOD_SHIFT           0x0001
/*! @brief If this bit is set one or more Control keys were held down.
 *
 *  If this bit is set one or more Control keys were held down.
 */
#define GLFW_MOD_CONTROL         0x0002
/*! @brief If this bit is set one or more Alt keys were held down.
 *
 *  If this bit is set one or more Alt keys were held down.
 */
#define GLFW_MOD_ALT             0x0004
/*! @brief If this bit is set one or more Super keys were held down.
 *
 *  If this bit is set one or more Super keys were held down.
 */
#define GLFW_MOD_SUPER           0x0008
/*! @brief If this bit is set the Caps Lock key is enabled.
 *
 *  If this bit is set the Caps Lock key is enabled and the @ref
 *  GLFW_LOCK_KEY_MODS input mode is set.
 */
#define GLFW_MOD_CAPS_LOCK       0x0010
/*! @brief If this bit is set the Num Lock key is enabled.
 *
 *  If this bit is set the Num Lock key is enabled and the @ref
 *  GLFW_LOCK_KEY_MODS input mode is set.
 */
#define GLFW_MOD_NUM_LOCK        0x0020

/*! @} */

/*! @defgroup buttons Mouse buttons
 *  @brief Mouse button IDs.
 *
 *  See [mouse button input](@ref input_mouse_button) for how these are used.
 *
 *  @ingroup input
 *  @{ */
#define GLFW_MOUSE_BUTTON_1         0
#define GLFW_MOUSE_BUTTON_2         1
#define GLFW_MOUSE_BUTTON_3         2
#define GLFW_MOUSE_BUTTON_4         3
#define GLFW_MOUSE_BUTTON_5         4
#define GLFW_MOUSE_BUTTON_6         5
#define GLFW_MOUSE_BUTTON_7         6
#define GLFW_MOUSE_BUTTON_8         7
#define GLFW_MOUSE_BUTTON_LAST      GLFW_MOUSE_BUTTON_8
#define GLFW_MOUSE_BUTTON_LEFT      GLFW_MOUSE_BUTTON_1
#define GLFW_MOUSE_BUTTON_RIGHT     GLFW_MOUSE_BUTTON_2
#define GLFW_MOUSE_BUTTON_MIDDLE    GLFW_MOUSE_BUTTON_3
/*! @} */

/*! @defgroup joysticks Joysticks
 *  @brief Joystick IDs.
 *
 *  See [joystick input](@ref joystick) for how these are used.
 *
 *  @ingroup input
 *  @{ */
#define GLFW_JOYSTICK_1             0
#define GLFW_JOYSTICK_2             1
#define GLFW_JOYSTICK_3             2
#define GLFW_JOYSTICK_4             3
#define GLFW_JOYSTICK_5             4
#define GLFW_JOYSTICK_6             5
#define GLFW_JOYSTICK_7             6
#define GLFW_JOYSTICK_8             7
#define GLFW_JOYSTICK_9             8
#define GLFW_JOYSTICK_10            9
#define GLFW_JOYSTICK_11            10
#define GLFW_JOYSTICK_12            11
#define GLFW_JOYSTICK_13            12
#define GLFW_JOYSTICK_14            13
#define GLFW_JOYSTICK_15            14
#define GLFW_JOYSTICK_16            15
#define GLFW_JOYSTICK_LAST          GLFW_JOYSTICK_16
/*! @} */

/*! @defgroup gamepad_buttons Gamepad buttons
 *  @brief Gamepad buttons.
 *
 *  See @ref gamepad for how these are used.
 *
 *  @ingroup input
 *  @{ */
#define GLFW_GAMEPAD_BUTTON_A               0
#define GLFW_GAMEPAD_BUTTON_B               1
#define GLFW_GAMEPAD_BUTTON_X               2
#define GLFW_GAMEPAD_BUTTON_Y               3
#define GLFW_GAMEPAD_BUTTON_LEFT_BUMPER     4
#define GLFW_GAMEPAD_BUTTON_RIGHT_BUMPER    5
#define GLFW_GAMEPAD_BUTTON_BACK            6
#define GLFW_GAMEPAD_BUTTON_START           7
#define GLFW_GAMEPAD_BUTTON_GUIDE           8
#define GLFW_GAMEPAD_BUTTON_LEFT_THUMB      9
#define GLFW_GAMEPAD_BUTTON_RIGHT_THUMB     10
#define GLFW_GAMEPAD_BUTTON_DPAD_UP         11
#define GLFW_GAMEPAD_BUTTON_DPAD_RIGHT      12
#define GLFW_GAMEPAD_BUTTON_DPAD_DOWN       13
#define GLFW_GAMEPAD_BUTTON_DPAD_LEFT       14
#define GLFW_GAMEPAD_BUTTON_LAST            GLFW_GAMEPAD_BUTTON_DPAD_LEFT

#define GLFW_GAMEPAD_BUTTON_CROSS       GLFW_GAMEPAD_BUTTON_A
#define GLFW_GAMEPAD_BUTTON_CIRCLE      GLFW_GAMEPAD_BUTTON_B
#define GLFW_GAMEPAD_BUTTON_SQUARE      GLFW_GAMEPAD_BUTTON_X
#define GLFW_GAMEPAD_BUTTON_TRIANGLE    GLFW_GAMEPAD_BUTTON_Y
/*! @} */

/*! @defgroup gamepad_axes Gamepad axes
 *  @brief Gamepad axes.
 *
 *  See @ref gamepad for how these are used.
 *
 *  @ingroup input
 *  @{ */
#define GLFW_GAMEPAD_AXIS_LEFT_X        0
#define GLFW_GAMEPAD_AXIS_LEFT_Y        1
#define GLFW_GAMEPAD_AXIS_RIGHT_X       2
#define GLFW_GAMEPAD_AXIS_RIGHT_Y       3
#define GLFW_GAMEPAD_AXIS_LEFT_TRIGGER  4
#define GLFW_GAMEPAD_AXIS_RIGHT_TRIGGER 5
#define GLFW_GAMEPAD_AXIS_LAST          GLFW_GAMEPAD_AXIS_RIGHT_TRIGGER
/*! @} */

/*! @defgroup errors Error codes
 *  @brief Error codes.
 *
 *  See [error handling](@ref error_handling) for how these are used.
 *
 *  @ingroup init
 *  @{ */
/*! @brief No error has occurred.
 *
 *  No error has occurred.
 *
 *  @analysis Yay.
 */
#define GLFW_NO_ERROR               0
/*! @brief GLFW has not been initialized.
 *
 *  This occurs if a GLFW function was called that must not be called unless the
 *  library is [initialized](@ref intro_init).
 *
 *  @analysis Application programmer error.  Initialize GLFW before calling any
 *  function that requires initialization.
 */
#define GLFW_NOT_INITIALIZED        0x00010001
/*! @brief No context is current for this thread.
 *
 *  This occurs if a GLFW function was called that needs and operates on the
 *  current OpenGL or OpenGL ES context but no context is current on the calling
 *  thread.  One such function is @ref glfwSwapInterval.
 *
 *  @analysis Application programmer error.  Ensure a context is current before
 *  calling functions that require a current context.
 */
#define GLFW_NO_CURRENT_CONTEXT     0x00010002
/*! @brief One of the arguments to the function was an invalid enum value.
 *
 *  One of the arguments to the function was an invalid enum value, for example
 *  requesting @ref GLFW_RED_BITS with @ref glfwGetWindowAttrib.
 *
 *  @analysis Application programmer error.  Fix the offending call.
 */
#define GLFW_INVALID_ENUM           0x00010003
/*! @brief One of the arguments to the function was an invalid value.
 *
 *  One of the arguments to the function was an invalid value, for example
 *  requesting a non-existent OpenGL or OpenGL ES version like 2.7.
 *
 *  Requesting a valid but unavailable OpenGL or OpenGL ES version will instead
 *  result in a @ref GLFW_VERSION_UNAVAILABLE error.
 *
 *  @analysis Application programmer error.  Fix the offending call.
 */
#define GLFW_INVALID_VALUE          0x00010004
/*! @brief A memory allocation failed.
 *
 *  A memory allocation failed.
 *
 *  @analysis A bug in GLFW or the underlying operating system.  Report the bug
 *  to our [issue tracker](https://github.com/glfw/glfw/issues).
 */
#define GLFW_OUT_OF_MEMORY          0x00010005
/*! @brief GLFW could not find support for the requested API on the system.
 *
 *  GLFW could not find support for the requested API on the system.
 *
 *  @analysis The installed graphics driver does not support the requested
 *  API, or does not support it via the chosen context creation backend.
 *  Below are a few examples.
 *
 *  @par
 *  Some pre-installed Windows graphics drivers do not support OpenGL.  AMD only
 *  supports OpenGL ES via EGL, while Nvidia and Intel only support it via
 *  a WGL or GLX extension.  macOS does not provide OpenGL ES at all.  The Mesa
 *  EGL, OpenGL and OpenGL ES libraries do not interface with the Nvidia binary
 *  driver.  Older graphics drivers do not support Vulkan.
 */
#define GLFW_API_UNAVAILABLE        0x00010006
/*! @brief The requested OpenGL or OpenGL ES version is not available.
 *
 *  The requested OpenGL or OpenGL ES version (including any requested context
 *  or framebuffer hints) is not available on this machine.
 *
 *  @analysis The machine does not support your requirements.  If your
 *  application is sufficiently flexible, downgrade your requirements and try
 *  again.  Otherwise, inform the user that their machine does not match your
 *  requirements.
 *
 *  @par
 *  Future invalid OpenGL and OpenGL ES versions, for example OpenGL 4.8 if 5.0
 *  comes out before the 4.x series gets that far, also fail with this error and
 *  not @ref GLFW_INVALID_VALUE, because GLFW cannot know what future versions
 *  will exist.
 */
#define GLFW_VERSION_UNAVAILABLE    0x00010007
/*! @brief A platform-specific error occurred that does not match any of the
 *  more specific categories.
 *
 *  A platform-specific error occurred that does not match any of the more
 *  specific categories.
 *
 *  @analysis A bug or configuration error in GLFW, the underlying operating
 *  system or its drivers, or a lack of required resources.  Report the issue to
 *  our [issue tracker](https://github.com/glfw/glfw/issues).
 */
#define GLFW_PLATFORM_ERROR         0x00010008
/*! @brief The requested format is not supported or available.
 *
 *  If emitted during window creation, the requested pixel format is not
 *  supported.
 *
 *  If emitted when querying the clipboard, the contents of the clipboard could
 *  not be converted to the requested format.
 *
 *  @analysis If emitted during window creation, one or more
 *  [hard constraints](@ref window_hints_hard) did not match any of the
 *  available pixel formats.  If your application is sufficiently flexible,
 *  downgrade your requirements and try again.  Otherwise, inform the user that
 *  their machine does not match your requirements.
 *
 *  @par
 *  If emitted when querying the clipboard, ignore the error or report it to
 *  the user, as appropriate.
 */
#define GLFW_FORMAT_UNAVAILABLE     0x00010009
/*! @brief The specified window does not have an OpenGL or OpenGL ES context.
 *
 *  A window that does not have an OpenGL or OpenGL ES context was passed to
 *  a function that requires it to have one.
 *
 *  @analysis Application programmer error.  Fix the offending call.
 */
#define GLFW_NO_WINDOW_CONTEXT      0x0001000A
/*! @} */

/*! @addtogroup window
 *  @{ */
/*! @brief Input focus window hint and attribute
 *
 *  Input focus [window hint](@ref GLFW_FOCUSED_hint) or
 *  [window attribute](@ref GLFW_FOCUSED_attrib).
 */
#define GLFW_FOCUSED                0x00020001
/*! @brief Window iconification window attribute
 *
 *  Window iconification [window attribute](@ref GLFW_ICONIFIED_attrib).
 */
#define GLFW_ICONIFIED              0x00020002
/*! @brief Window resize-ability window hint and attribute
 *
 *  Window resize-ability [window hint](@ref GLFW_RESIZABLE_hint) and
 *  [window attribute](@ref GLFW_RESIZABLE_attrib).
 */
#define GLFW_RESIZABLE              0x00020003
/*! @brief Window visibility window hint and attribute
 *
 *  Window visibility [window hint](@ref GLFW_VISIBLE_hint) and
 *  [window attribute](@ref GLFW_VISIBLE_attrib).
 */
#define GLFW_VISIBLE                0x00020004
/*! @brief Window decoration window hint and attribute
 *
 *  Window decoration [window hint](@ref GLFW_DECORATED_hint) and
 *  [window attribute](@ref GLFW_DECORATED_attrib).
 */
#define GLFW_DECORATED              0x00020005
/*! @brief Window auto-iconification window hint and attribute
 *
 *  Window auto-iconification [window hint](@ref GLFW_AUTO_ICONIFY_hint) and
 *  [window attribute](@ref GLFW_AUTO_ICONIFY_attrib).
 */
#define GLFW_AUTO_ICONIFY           0x00020006
/*! @brief Window decoration window hint and attribute
 *
 *  Window decoration [window hint](@ref GLFW_FLOATING_hint) and
 *  [window attribute](@ref GLFW_FLOATING_attrib).
 */
#define GLFW_FLOATING               0x00020007
/*! @brief Window maximization window hint and attribute
 *
 *  Window maximization [window hint](@ref GLFW_MAXIMIZED_hint) and
 *  [window attribute](@ref GLFW_MAXIMIZED_attrib).
 */
#define GLFW_MAXIMIZED              0x00020008
/*! @brief Cursor centering window hint
 *
 *  Cursor centering [window hint](@ref GLFW_CENTER_CURSOR_hint).
 */
#define GLFW_CENTER_CURSOR          0x00020009
/*! @brief Window framebuffer transparency hint and attribute
 *
 *  Window framebuffer transparency
 *  [window hint](@ref GLFW_TRANSPARENT_FRAMEBUFFER_hint) and
 *  [window attribute](@ref GLFW_TRANSPARENT_FRAMEBUFFER_attrib).
 */
#define GLFW_TRANSPARENT_FRAMEBUFFER 0x0002000A
/*! @brief Mouse cursor hover window attribute.
 *
 *  Mouse cursor hover [window attribute](@ref GLFW_HOVERED_attrib).
 */
#define GLFW_HOVERED                0x0002000B
/*! @brief Input focus on calling show window hint and attribute
 *
 *  Input focus [window hint](@ref GLFW_FOCUS_ON_SHOW_hint) or
 *  [window attribute](@ref GLFW_FOCUS_ON_SHOW_attrib).
 */
#define GLFW_FOCUS_ON_SHOW          0x0002000C
/*! @brief Occlusion window attribute
 *
 *  Occlusion [window attribute](@ref GLFW_OCCLUDED_attrib).
 */
#define GLFW_OCCLUDED               0x0002000D
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_RED_BITS).
 */
#define GLFW_RED_BITS               0x00021001
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_GREEN_BITS).
 */
#define GLFW_GREEN_BITS             0x00021002
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_BLUE_BITS).
 */
#define GLFW_BLUE_BITS              0x00021003
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_ALPHA_BITS).
 */
#define GLFW_ALPHA_BITS             0x00021004
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_DEPTH_BITS).
 */
#define GLFW_DEPTH_BITS             0x00021005
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_STENCIL_BITS).
 */
#define GLFW_STENCIL_BITS           0x00021006
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_ACCUM_RED_BITS).
 */
#define GLFW_ACCUM_RED_BITS         0x00021007
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_ACCUM_GREEN_BITS).
 */
#define GLFW_ACCUM_GREEN_BITS       0x00021008
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_ACCUM_BLUE_BITS).
 */
#define GLFW_ACCUM_BLUE_BITS        0x00021009
/*! @brief Framebuffer bit depth hint.
 *
 *  Framebuffer bit depth [hint](@ref GLFW_ACCUM_ALPHA_BITS).
 */
#define GLFW_ACCUM_ALPHA_BITS       0x0002100A
/*! @brief Framebuffer auxiliary buffer hint.
 *
 *  Framebuffer auxiliary buffer [hint](@ref GLFW_AUX_BUFFERS).
 */
#define GLFW_AUX_BUFFERS            0x0002100B
/*! @brief OpenGL stereoscopic rendering hint.
 *
 *  OpenGL stereoscopic rendering [hint](@ref GLFW_STEREO).
 */
#define GLFW_STEREO                 0x0002100C
/*! @brief Framebuffer MSAA samples hint.
 *
 *  Framebuffer MSAA samples [hint](@ref GLFW_SAMPLES).
 */
#define GLFW_SAMPLES                0x0002100D
/*! @brief Framebuffer sRGB hint.
 *
 *  Framebuffer sRGB [hint](@ref GLFW_SRGB_CAPABLE).
 */
#define GLFW_SRGB_CAPABLE           0x0002100E
/*! @brief Monitor refresh rate hint.
 *
 *  Monitor refresh rate [hint](@ref GLFW_REFRESH_RATE).
 */
#define GLFW_REFRESH_RATE           0x0002100F
/*! @brief Framebuffer double buffering hint.
 *
 *  Framebuffer double buffering [hint](@ref GLFW_DOUBLEBUFFER).
 */
#define GLFW_DOUBLEBUFFER           0x00021010

/*! @brief Context client API hint and attribute.
 *
 *  Context client API [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CLIENT_API             0x00022001
/*! @brief Context client API major version hint and attribute.
 *
 *  Context client API major version [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CONTEXT_VERSION_MAJOR  0x00022002
/*! @brief Context client API minor version hint and attribute.
 *
 *  Context client API minor version [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CONTEXT_VERSION_MINOR  0x00022003
/*! @brief Context client API revision number hint and attribute.
 *
 *  Context client API revision number [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CONTEXT_REVISION       0x00022004
/*! @brief Context robustness hint and attribute.
 *
 *  Context client API revision number [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CONTEXT_ROBUSTNESS     0x00022005
/*! @brief OpenGL forward-compatibility hint and attribute.
 *
 *  OpenGL forward-compatibility [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_OPENGL_FORWARD_COMPAT  0x00022006
/*! @brief OpenGL debug context hint and attribute.
 *
 *  OpenGL debug context [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_OPENGL_DEBUG_CONTEXT   0x00022007
/*! @brief OpenGL profile hint and attribute.
 *
 *  OpenGL profile [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_OPENGL_PROFILE         0x00022008
/*! @brief Context flush-on-release hint and attribute.
 *
 *  Context flush-on-release [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CONTEXT_RELEASE_BEHAVIOR 0x00022009
/*! @brief Context error suppression hint and attribute.
 *
 *  Context error suppression [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CONTEXT_NO_ERROR       0x0002200A
/*! @brief Context creation API hint and attribute.
 *
 *  Context creation API [hint](@ref GLFW_CLIENT_API_hint) and
 *  [attribute](@ref GLFW_CLIENT_API_attrib).
 */
#define GLFW_CONTEXT_CREATION_API   0x0002200B
/*! @brief Window content area scaling window
 *  [window hint](@ref GLFW_SCALE_TO_MONITOR).
 */
#define GLFW_SCALE_TO_MONITOR       0x0002200C

#define GLFW_COCOA_RETINA_FRAMEBUFFER 0x00023001
#define GLFW_COCOA_FRAME_NAME         0x00023002
#define GLFW_COCOA_GRAPHICS_SWITCHING 0x00023003

#define GLFW_X11_CLASS_NAME         0x00024001
#define GLFW_X11_INSTANCE_NAME      0x00024002

#define GLFW_WAYLAND_APP_ID         0x00025001
/*! @} */

#define GLFW_NO_API                          0
#define GLFW_OPENGL_API             0x00030001
#define GLFW_OPENGL_ES_API          0x00030002

#define GLFW_NO_ROBUSTNESS                   0
#define GLFW_NO_RESET_NOTIFICATION  0x00031001
#define GLFW_LOSE_CONTEXT_ON_RESET  0x00031002

#define GLFW_OPENGL_ANY_PROFILE              0
#define GLFW_OPENGL_CORE_PROFILE    0x00032001
#define GLFW_OPENGL_COMPAT_PROFILE  0x00032002

#define GLFW_CURSOR                 0x00033001
#define GLFW_STICKY_KEYS            0x00033002
#define GLFW_STICKY_MOUSE_BUTTONS   0x00033003
#define GLFW_LOCK_KEY_MODS          0x00033004

#define GLFW_CURSOR_NORMAL          0x00034001
#define GLFW_CURSOR_HIDDEN          0x00034002
#define GLFW_CURSOR_DISABLED        0x00034003

#define GLFW_ANY_RELEASE_BEHAVIOR            0
#define GLFW_RELEASE_BEHAVIOR_FLUSH 0x00035001
#define GLFW_RELEASE_BEHAVIOR_NONE  0x00035002

#define GLFW_NATIVE_CONTEXT_API     0x00036001
#define GLFW_EGL_CONTEXT_API        0x00036002
#define GLFW_OSMESA_CONTEXT_API     0x00036003

/*! @defgroup shapes Standard cursor shapes
 *  @brief Standard system cursor shapes.
 *
 *  See [standard cursor creation](@ref cursor_standard) for how these are used.
 *
 *  @ingroup input
 *  @{ */

typedef enum {
    GLFW_ARROW_CURSOR,
    GLFW_IBEAM_CURSOR,
    GLFW_CROSSHAIR_CURSOR,
    GLFW_HAND_CURSOR,
    GLFW_HRESIZE_CURSOR,
    GLFW_VRESIZE_CURSOR,
    GLFW_NW_RESIZE_CURSOR,
    GLFW_NE_RESIZE_CURSOR,
    GLFW_SW_RESIZE_CURSOR,
    GLFW_SE_RESIZE_CURSOR,
    GLFW_INVALID_CURSOR
} GLFWCursorShape;
/*! @} */

#define GLFW_CONNECTED              0x00040001
#define GLFW_DISCONNECTED           0x00040002

/*! @addtogroup init
 *  @{ */
#define GLFW_JOYSTICK_HAT_BUTTONS   0x00050001
#define GLFW_DEBUG_KEYBOARD         0x00050002
#define GLFW_ENABLE_JOYSTICKS       0x00050003

#define GLFW_COCOA_CHDIR_RESOURCES  0x00051001
#define GLFW_COCOA_MENUBAR          0x00051002
/*! @} */

#define GLFW_DONT_CARE              -1


/*************************************************************************
 * GLFW API types
 *************************************************************************/

/*! @brief Client API function pointer type.
 *
 *  Generic function pointer used for returning client API function pointers
 *  without forcing a cast from a regular pointer.
 *
 *  @sa @ref context_glext
 *  @sa @ref glfwGetProcAddress
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup context
 */
typedef void (*GLFWglproc)(void);

/*! @brief Vulkan API function pointer type.
 *
 *  Generic function pointer used for returning Vulkan API function pointers
 *  without forcing a cast from a regular pointer.
 *
 *  @sa @ref vulkan_proc
 *  @sa @ref glfwGetInstanceProcAddress
 *
 *  @since Added in version 3.2.
 *
 *  @ingroup vulkan
 */
typedef void (*GLFWvkproc)(void);

/*! @brief Opaque monitor object.
 *
 *  Opaque monitor object.
 *
 *  @see @ref monitor_object
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup monitor
 */
typedef struct GLFWmonitor GLFWmonitor;

/*! @brief Opaque window object.
 *
 *  Opaque window object.
 *
 *  @see @ref window_object
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup window
 */
typedef struct GLFWwindow GLFWwindow;

/*! @brief Opaque cursor object.
 *
 *  Opaque cursor object.
 *
 *  @see @ref cursor_object
 *
 *  @since Added in version 3.1.
 *
 *  @ingroup cursor
 */
typedef struct GLFWcursor GLFWcursor;

/*! @brief The function signature for error callbacks.
 *
 *  This is the function signature for error callback functions.
 *
 *  @param[in] error An [error code](@ref errors).
 *  @param[in] description A UTF-8 encoded string describing the error.
 *
 *  @sa @ref error_handling
 *  @sa @ref glfwSetErrorCallback
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup init
 */
typedef void (* GLFWerrorfun)(int,const char*);

/*! @brief The function signature for window position callbacks.
 *
 *  This is the function signature for window position callback functions.
 *
 *  @param[in] window The window that was moved.
 *  @param[in] xpos The new x-coordinate, in screen coordinates, of the
 *  upper-left corner of the content area of the window.
 *  @param[in] ypos The new y-coordinate, in screen coordinates, of the
 *  upper-left corner of the content area of the window.
 *
 *  @sa @ref window_pos
 *  @sa @ref glfwSetWindowPosCallback
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowposfun)(GLFWwindow*,int,int);

/*! @brief The function signature for window resize callbacks.
 *
 *  This is the function signature for window size callback functions.
 *
 *  @param[in] window The window that was resized.
 *  @param[in] width The new width, in screen coordinates, of the window.
 *  @param[in] height The new height, in screen coordinates, of the window.
 *
 *  @sa @ref window_size
 *  @sa @ref glfwSetWindowSizeCallback
 *
 *  @since Added in version 1.0.
 *  @glfw3 Added window handle parameter.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowsizefun)(GLFWwindow*,int,int);

/*! @brief The function signature for window close callbacks.
 *
 *  This is the function signature for window close callback functions.
 *
 *  @param[in] window The window that the user attempted to close.
 *
 *  @sa @ref window_close
 *  @sa @ref glfwSetWindowCloseCallback
 *
 *  @since Added in version 2.5.
 *  @glfw3 Added window handle parameter.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowclosefun)(GLFWwindow*);

/*! @brief The function signature for window content refresh callbacks.
 *
 *  This is the function signature for window refresh callback functions.
 *
 *  @param[in] window The window whose content needs to be refreshed.
 *
 *  @sa @ref window_refresh
 *  @sa @ref glfwSetWindowRefreshCallback
 *
 *  @since Added in version 2.5.
 *  @glfw3 Added window handle parameter.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowrefreshfun)(GLFWwindow*);

/*! @brief The function signature for window focus/defocus callbacks.
 *
 *  This is the function signature for window focus callback functions.
 *
 *  @param[in] window The window that gained or lost input focus.
 *  @param[in] focused `GLFW_TRUE` if the window was given input focus, or
 *  `GLFW_FALSE` if it lost it.
 *
 *  @sa @ref window_focus
 *  @sa @ref glfwSetWindowFocusCallback
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowfocusfun)(GLFWwindow*,int);

/*! @brief The function signature for window occlusion callbacks.
 *
 *  This is the function signature for window occlusion callback functions.
 *
 *  @param[in] window The window whose occlusion state changed.
 *  @param[in] occluded `GLFW_TRUE` if the window was occluded, or `GLFW_FALSE`
 *  if the window is no longer occluded.
 *
 *  @sa @ref window_occlusion
 *  @sa @ref glfwSetWindowOcclusionCallback
 *
 *  @since Added in version 3.3.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowocclusionfun)(GLFWwindow*, bool);


/*! @brief The function signature for window iconify/restore callbacks.
 *
 *  This is the function signature for window iconify/restore callback
 *  functions.
 *
 *  @param[in] window The window that was iconified or restored.
 *  @param[in] iconified `GLFW_TRUE` if the window was iconified, or
 *  `GLFW_FALSE` if it was restored.
 *
 *  @sa @ref window_iconify
 *  @sa @ref glfwSetWindowIconifyCallback
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowiconifyfun)(GLFWwindow*,int);

/*! @brief The function signature for window maximize/restore callbacks.
 *
 *  This is the function signature for window maximize/restore callback
 *  functions.
 *
 *  @param[in] window The window that was maximized or restored.
 *  @param[in] iconified `GLFW_TRUE` if the window was maximized, or
 *  `GLFW_FALSE` if it was restored.
 *
 *  @sa @ref window_maximize
 *  @sa glfwSetWindowMaximizeCallback
 *
 *  @since Added in version 3.3.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowmaximizefun)(GLFWwindow*,int);

/*! @brief The function signature for framebuffer resize callbacks.
 *
 *  This is the function signature for framebuffer resize callback
 *  functions.
 *
 *  @param[in] window The window whose framebuffer was resized.
 *  @param[in] width The new width, in pixels, of the framebuffer.
 *  @param[in] height The new height, in pixels, of the framebuffer.
 *
 *  @sa @ref window_fbsize
 *  @sa @ref glfwSetFramebufferSizeCallback
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup window
 */
typedef void (* GLFWframebuffersizefun)(GLFWwindow*,int,int);

/*! @brief The function signature for window content scale callbacks.
 *
 *  This is the function signature for window content scale callback
 *  functions.
 *
 *  @param[in] window The window whose content scale changed.
 *  @param[in] xscale The new x-axis content scale of the window.
 *  @param[in] yscale The new y-axis content scale of the window.
 *
 *  @sa @ref window_scale
 *  @sa @ref glfwSetWindowContentScaleCallback
 *
 *  @since Added in version 3.3.
 *
 *  @ingroup window
 */
typedef void (* GLFWwindowcontentscalefun)(GLFWwindow*,float,float);

/*! @brief The function signature for mouse button callbacks.
 *
 *  This is the function signature for mouse button callback functions.
 *
 *  @param[in] window The window that received the event.
 *  @param[in] button The [mouse button](@ref buttons) that was pressed or
 *  released.
 *  @param[in] action One of `GLFW_PRESS` or `GLFW_RELEASE`.
 *  @param[in] mods Bit field describing which [modifier keys](@ref mods) were
 *  held down.
 *
 *  @sa @ref input_mouse_button
 *  @sa @ref glfwSetMouseButtonCallback
 *
 *  @since Added in version 1.0.
 *  @glfw3 Added window handle and modifier mask parameters.
 *
 *  @ingroup input
 */
typedef void (* GLFWmousebuttonfun)(GLFWwindow*,int,int,int);

/*! @brief The function signature for cursor position callbacks.
 *
 *  This is the function signature for cursor position callback functions.
 *
 *  @param[in] window The window that received the event.
 *  @param[in] xpos The new cursor x-coordinate, relative to the left edge of
 *  the content area.
 *  @param[in] ypos The new cursor y-coordinate, relative to the top edge of the
 *  content area.
 *
 *  @sa @ref cursor_pos
 *  @sa @ref glfwSetCursorPosCallback
 *
 *  @since Added in version 3.0.  Replaces `GLFWmouseposfun`.
 *
 *  @ingroup input
 */
typedef void (* GLFWcursorposfun)(GLFWwindow*,double,double);

/*! @brief The function signature for cursor enter/leave callbacks.
 *
 *  This is the function signature for cursor enter/leave callback functions.
 *
 *  @param[in] window The window that received the event.
 *  @param[in] entered `GLFW_TRUE` if the cursor entered the window's client
 *  area, or `GLFW_FALSE` if it left it.
 *
 *  @sa @ref cursor_enter
 *  @sa @ref glfwSetCursorEnterCallback
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup input
 */
typedef void (* GLFWcursorenterfun)(GLFWwindow*,int);

/*! @brief The function signature for scroll callbacks.
 *
 *  This is the function signature for scroll callback functions.
 *
 *  @param[in] window The window that received the event.
 *  @param[in] xoffset The scroll offset along the x-axis.
 *  @param[in] yoffset The scroll offset along the y-axis.
 *  @param[in] flags A bit-mask providing extra data about the event.
 *  flags & 1 will be true if and only if the offset values are "high-precision".
 *  Typically pixel values. Otherwise the offset values are number of lines.
 *  (flags >> 1) & 7 will have value 1 for the start of momentum scrolling,
 *  value 2 for stationary momentum scrolling, value 3 for momentum scrolling
 *  in progress, value 4 for momentum scrolling ended, value 5 for momentum
 *  scrolling cancelled and value 6 if scrolling may begin soon.
 *
 *  @sa @ref scrolling
 *  @sa @ref glfwSetScrollCallback
 *
 *  @since Added in version 3.0.  Replaces `GLFWmousewheelfun`.
 *  @since Changed in version 4.0.  Added `flags` parameter.
 *
 *  @ingroup input
 */
typedef void (* GLFWscrollfun)(GLFWwindow*,double,double,int);

/*! @brief The function signature for key callbacks.
 *
 *  This is the function signature for key callback functions.
 *  The semantics of this function are that the key that is interacted with on the
 *  keyboard is reported, and the text, if any generated by the key is reported.
 *  So, for example, if on a US-ASCII keyboard the user presses Shift+= GLFW
 *  will report the text "+" and the key as GLFW_KEY_EQUAL. The reported key takes into
 *  account any current keyboard maps defined in the OS. So with a dvorak mapping, pressing
 *  the "s" key will generate text "o" and GLFW_KEY_O.
 *
 *  @param[in] window The window that received the event.
 *  @param[in] key The [keyboard key](@ref keys) that was pressed or released.
 *  @param[in] scancode The system-specific scancode of the key.
 *  @param[in] action `GLFW_PRESS`, `GLFW_RELEASE` or `GLFW_REPEAT`.
 *  @param[in] mods Bit field describing which [modifier keys](@ref mods) were
 *  held down.
 *  @param[in] text UTF-8 encoded text generated by this key event or empty string.
 *  @param[in] Used for Input Method events. Zero for normal key events.
 *      A value of 1 means the pre-edit text for the input event has been changed.
 *      A value of 2 means the text should be committed.
 *
 *  @note On X11/Wayland if a modifier other than the modifiers GLFW reports
 *  (ctrl/shift/alt/super) is used, GLFW will report the shifted key rather
 *  than the unshifted key. So for example, if ISO_Shift_Level_5 is used to
 *  convert the key A into UP GLFW will report the key as UP with no modifiers.
 *
 *  @sa @ref input_key
 *  @sa @ref glfwSetKeyboardCallback
 *
 *  @since Added in version 4.0.
 *
 *  @ingroup input
 */
typedef void (* GLFWkeyboardfun)(GLFWwindow*, int, int, int, int, const char*, int);

/*! @brief The function signature for file drop callbacks.
 *
 *  This is the function signature for file drop callbacks.
 *
 *  @param[in] window The window that received the event.
 *  @param[in] count The number of dropped files.
 *  @param[in] paths The UTF-8 encoded file and/or directory path names.
 *
 *  @sa @ref path_drop
 *  @sa @ref glfwSetDropCallback
 *
 *  @since Added in version 3.1.
 *
 *  @ingroup input
 */
typedef void (* GLFWdropfun)(GLFWwindow*,int,const char**);

typedef void (* GLFWliveresizefun)(GLFWwindow*, bool);

/*! @brief The function signature for monitor configuration callbacks.
 *
 *  This is the function signature for monitor configuration callback functions.
 *
 *  @param[in] monitor The monitor that was connected or disconnected.
 *  @param[in] event One of `GLFW_CONNECTED` or `GLFW_DISCONNECTED`.  Remaining
 *  values reserved for future use.
 *
 *  @sa @ref monitor_event
 *  @sa @ref glfwSetMonitorCallback
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup monitor
 */
typedef void (* GLFWmonitorfun)(GLFWmonitor*,int);

/*! @brief The function signature for joystick configuration callbacks.
 *
 *  This is the function signature for joystick configuration callback
 *  functions.
 *
 *  @param[in] jid The joystick that was connected or disconnected.
 *  @param[in] event One of `GLFW_CONNECTED` or `GLFW_DISCONNECTED`.  Remaining
 *  values reserved for future use.
 *
 *  @sa @ref joystick_event
 *  @sa @ref glfwSetJoystickCallback
 *
 *  @since Added in version 3.2.
 *
 *  @ingroup input
 */
typedef void (* GLFWjoystickfun)(int,int);

typedef void (* GLFWuserdatafun)(unsigned long long, void*);
typedef void (* GLFWtickcallback)(void*);

/*! @brief Video mode type.
 *
 *  This describes a single video mode.
 *
 *  @sa @ref monitor_modes
 *  @sa @ref glfwGetVideoMode
 *  @sa @ref glfwGetVideoModes
 *
 *  @since Added in version 1.0.
 *  @glfw3 Added refresh rate member.
 *
 *  @ingroup monitor
 */
typedef struct GLFWvidmode
{
    /*! The width, in screen coordinates, of the video mode.
     */
    int width;
    /*! The height, in screen coordinates, of the video mode.
     */
    int height;
    /*! The bit depth of the red channel of the video mode.
     */
    int redBits;
    /*! The bit depth of the green channel of the video mode.
     */
    int greenBits;
    /*! The bit depth of the blue channel of the video mode.
     */
    int blueBits;
    /*! The refresh rate, in Hz, of the video mode.
     */
    int refreshRate;
} GLFWvidmode;

/*! @brief Gamma ramp.
 *
 *  This describes the gamma ramp for a monitor.
 *
 *  @sa @ref monitor_gamma
 *  @sa @ref glfwGetGammaRamp
 *  @sa @ref glfwSetGammaRamp
 *
 *  @since Added in version 3.0.
 *
 *  @ingroup monitor
 */
typedef struct GLFWgammaramp
{
    /*! An array of value describing the response of the red channel.
     */
    unsigned short* red;
    /*! An array of value describing the response of the green channel.
     */
    unsigned short* green;
    /*! An array of value describing the response of the blue channel.
     */
    unsigned short* blue;
    /*! The number of elements in each array.
     */
    unsigned int size;
} GLFWgammaramp;

/*! @brief Image data.
 *
 *  This describes a single 2D image.  See the documentation for each related
 *  function what the expected pixel format is.
 *
 *  @sa @ref cursor_custom
 *  @sa @ref window_icon
 *
 *  @since Added in version 2.1.
 *  @glfw3 Removed format and bytes-per-pixel members.
 */
typedef struct GLFWimage
{
    /*! The width, in pixels, of this image.
     */
    int width;
    /*! The height, in pixels, of this image.
     */
    int height;
    /*! The pixel data of this image, arranged left-to-right, top-to-bottom.
     */
    unsigned char* pixels;
} GLFWimage;

/*! @brief Gamepad input state
 *
 *  This describes the input state of a gamepad.
 *
 *  @sa @ref gamepad
 *  @sa @ref glfwGetGamepadState
 *
 *  @since Added in version 3.3.
 */
typedef struct GLFWgamepadstate
{
    /*! The states of each [gamepad button](@ref gamepad_buttons), `GLFW_PRESS`
     *  or `GLFW_RELEASE`.
     */
    unsigned char buttons[15];
    /*! The states of each [gamepad axis](@ref gamepad_axes), in the range -1.0
     *  to 1.0 inclusive.
     */
    float axes[6];
} GLFWgamepadstate;


/*************************************************************************
 * GLFW API functions
 *************************************************************************/

/*! @brief Initializes the GLFW library.
 *
 *  This function initializes the GLFW library.  Before most GLFW functions can
 *  be used, GLFW must be initialized, and before an application terminates GLFW
 *  should be terminated in order to free any resources allocated during or
 *  after initialization.
 *
 *  If this function fails, it calls @ref glfwTerminate before returning.  If it
 *  succeeds, you should call @ref glfwTerminate before the application exits.
 *
 *  Additional calls to this function after successful initialization but before
 *  termination will return `GLFW_TRUE` immediately.
 *
 *  @return `GLFW_TRUE` if successful, or `GLFW_FALSE` if an
 *  [error](@ref error_handling) occurred.
 *
 *  @errors Possible errors include @ref GLFW_PLATFORM_ERROR.
 *
 *  @remark @macos This function will change the current directory of the
 *  application to the `Contents/Resources` subdirectory of the application's
 *  bundle, if present.  This can be disabled with the @ref
 *  GLFW_COCOA_CHDIR_RESOURCES init hint.
 *
 *  @thread_safety This function must only be called from the main thread.
 *
 *  @sa @ref intro_init
 *  @sa @ref glfwTerminate
 *
 *  @since Added in version 1.0.
 *
 *  @ingroup init
 */


typedef int (* GLFWcocoatextinputfilterfun)(int,int,unsigned int,unsigned long);
typedef int (* GLFWapplicationshouldhandlereopenfun)(int);
typedef int (* GLFWcocoatogglefullscreenfun)(GLFWwindow*);
typedef void (* GLFWcocoarenderframefun)(GLFWwindow*);
typedef void (*GLFWwaylandframecallbackfunc)(unsigned long long id);
typedef void (*GLFWDBusnotificationcreatedfun)(unsigned long long, uint32_t, void*);
typedef void (*GLFWDBusnotificationactivatedfun)(uint32_t, const char*);
typedef int (*glfwInit_func)();
glfwInit_func glfwInit_impl;
#define glfwInit glfwInit_impl

typedef void (*glfwRunMainLoop_func)(GLFWtickcallback, void*);
glfwRunMainLoop_func glfwRunMainLoop_impl;
#define glfwRunMainLoop glfwRunMainLoop_impl

typedef void (*glfwStopMainLoop_func)();
glfwStopMainLoop_func glfwStopMainLoop_impl;
#define glfwStopMainLoop glfwStopMainLoop_impl

typedef void (*glfwRequestTickCallback_func)();
glfwRequestTickCallback_func glfwRequestTickCallback_impl;
#define glfwRequestTickCallback glfwRequestTickCallback_impl

typedef unsigned long long (*glfwAddTimer_func)(double, bool, GLFWuserdatafun, void *, GLFWuserdatafun);
glfwAddTimer_func glfwAddTimer_impl;
#define glfwAddTimer glfwAddTimer_impl

typedef void (*glfwUpdateTimer_func)(unsigned long long, double, bool);
glfwUpdateTimer_func glfwUpdateTimer_impl;
#define glfwUpdateTimer glfwUpdateTimer_impl

typedef void (*glfwRemoveTimer_func)(unsigned long);
glfwRemoveTimer_func glfwRemoveTimer_impl;
#define glfwRemoveTimer glfwRemoveTimer_impl

typedef void (*glfwTerminate_func)();
glfwTerminate_func glfwTerminate_impl;
#define glfwTerminate glfwTerminate_impl

typedef void (*glfwInitHint_func)(int, int);
glfwInitHint_func glfwInitHint_impl;
#define glfwInitHint glfwInitHint_impl

typedef void (*glfwGetVersion_func)(int*, int*, int*);
glfwGetVersion_func glfwGetVersion_impl;
#define glfwGetVersion glfwGetVersion_impl

typedef const char* (*glfwGetVersionString_func)();
glfwGetVersionString_func glfwGetVersionString_impl;
#define glfwGetVersionString glfwGetVersionString_impl

typedef int (*glfwGetError_func)(const char**);
glfwGetError_func glfwGetError_impl;
#define glfwGetError glfwGetError_impl

typedef GLFWerrorfun (*glfwSetErrorCallback_func)(GLFWerrorfun);
glfwSetErrorCallback_func glfwSetErrorCallback_impl;
#define glfwSetErrorCallback glfwSetErrorCallback_impl

typedef GLFWmonitor** (*glfwGetMonitors_func)(int*);
glfwGetMonitors_func glfwGetMonitors_impl;
#define glfwGetMonitors glfwGetMonitors_impl

typedef GLFWmonitor* (*glfwGetPrimaryMonitor_func)();
glfwGetPrimaryMonitor_func glfwGetPrimaryMonitor_impl;
#define glfwGetPrimaryMonitor glfwGetPrimaryMonitor_impl

typedef void (*glfwGetMonitorPos_func)(GLFWmonitor*, int*, int*);
glfwGetMonitorPos_func glfwGetMonitorPos_impl;
#define glfwGetMonitorPos glfwGetMonitorPos_impl

typedef void (*glfwGetMonitorWorkarea_func)(GLFWmonitor*, int*, int*, int*, int*);
glfwGetMonitorWorkarea_func glfwGetMonitorWorkarea_impl;
#define glfwGetMonitorWorkarea glfwGetMonitorWorkarea_impl

typedef void (*glfwGetMonitorPhysicalSize_func)(GLFWmonitor*, int*, int*);
glfwGetMonitorPhysicalSize_func glfwGetMonitorPhysicalSize_impl;
#define glfwGetMonitorPhysicalSize glfwGetMonitorPhysicalSize_impl

typedef void (*glfwGetMonitorContentScale_func)(GLFWmonitor*, float*, float*);
glfwGetMonitorContentScale_func glfwGetMonitorContentScale_impl;
#define glfwGetMonitorContentScale glfwGetMonitorContentScale_impl

typedef const char* (*glfwGetMonitorName_func)(GLFWmonitor*);
glfwGetMonitorName_func glfwGetMonitorName_impl;
#define glfwGetMonitorName glfwGetMonitorName_impl

typedef void (*glfwSetMonitorUserPointer_func)(GLFWmonitor*, void*);
glfwSetMonitorUserPointer_func glfwSetMonitorUserPointer_impl;
#define glfwSetMonitorUserPointer glfwSetMonitorUserPointer_impl

typedef void* (*glfwGetMonitorUserPointer_func)(GLFWmonitor*);
glfwGetMonitorUserPointer_func glfwGetMonitorUserPointer_impl;
#define glfwGetMonitorUserPointer glfwGetMonitorUserPointer_impl

typedef GLFWmonitorfun (*glfwSetMonitorCallback_func)(GLFWmonitorfun);
glfwSetMonitorCallback_func glfwSetMonitorCallback_impl;
#define glfwSetMonitorCallback glfwSetMonitorCallback_impl

typedef const GLFWvidmode* (*glfwGetVideoModes_func)(GLFWmonitor*, int*);
glfwGetVideoModes_func glfwGetVideoModes_impl;
#define glfwGetVideoModes glfwGetVideoModes_impl

typedef const GLFWvidmode* (*glfwGetVideoMode_func)(GLFWmonitor*);
glfwGetVideoMode_func glfwGetVideoMode_impl;
#define glfwGetVideoMode glfwGetVideoMode_impl

typedef void (*glfwSetGamma_func)(GLFWmonitor*, float);
glfwSetGamma_func glfwSetGamma_impl;
#define glfwSetGamma glfwSetGamma_impl

typedef const GLFWgammaramp* (*glfwGetGammaRamp_func)(GLFWmonitor*);
glfwGetGammaRamp_func glfwGetGammaRamp_impl;
#define glfwGetGammaRamp glfwGetGammaRamp_impl

typedef void (*glfwSetGammaRamp_func)(GLFWmonitor*, const GLFWgammaramp*);
glfwSetGammaRamp_func glfwSetGammaRamp_impl;
#define glfwSetGammaRamp glfwSetGammaRamp_impl

typedef void (*glfwDefaultWindowHints_func)();
glfwDefaultWindowHints_func glfwDefaultWindowHints_impl;
#define glfwDefaultWindowHints glfwDefaultWindowHints_impl

typedef void (*glfwWindowHint_func)(int, int);
glfwWindowHint_func glfwWindowHint_impl;
#define glfwWindowHint glfwWindowHint_impl

typedef void (*glfwWindowHintString_func)(int, const char*);
glfwWindowHintString_func glfwWindowHintString_impl;
#define glfwWindowHintString glfwWindowHintString_impl

typedef GLFWwindow* (*glfwCreateWindow_func)(int, int, const char*, GLFWmonitor*, GLFWwindow*);
glfwCreateWindow_func glfwCreateWindow_impl;
#define glfwCreateWindow glfwCreateWindow_impl

typedef void (*glfwDestroyWindow_func)(GLFWwindow*);
glfwDestroyWindow_func glfwDestroyWindow_impl;
#define glfwDestroyWindow glfwDestroyWindow_impl

typedef int (*glfwWindowShouldClose_func)(GLFWwindow*);
glfwWindowShouldClose_func glfwWindowShouldClose_impl;
#define glfwWindowShouldClose glfwWindowShouldClose_impl

typedef void (*glfwSetWindowShouldClose_func)(GLFWwindow*, int);
glfwSetWindowShouldClose_func glfwSetWindowShouldClose_impl;
#define glfwSetWindowShouldClose glfwSetWindowShouldClose_impl

typedef void (*glfwSetWindowTitle_func)(GLFWwindow*, const char*);
glfwSetWindowTitle_func glfwSetWindowTitle_impl;
#define glfwSetWindowTitle glfwSetWindowTitle_impl

typedef void (*glfwSetWindowIcon_func)(GLFWwindow*, int, const GLFWimage*);
glfwSetWindowIcon_func glfwSetWindowIcon_impl;
#define glfwSetWindowIcon glfwSetWindowIcon_impl

typedef void (*glfwGetWindowPos_func)(GLFWwindow*, int*, int*);
glfwGetWindowPos_func glfwGetWindowPos_impl;
#define glfwGetWindowPos glfwGetWindowPos_impl

typedef void (*glfwSetWindowPos_func)(GLFWwindow*, int, int);
glfwSetWindowPos_func glfwSetWindowPos_impl;
#define glfwSetWindowPos glfwSetWindowPos_impl

typedef void (*glfwGetWindowSize_func)(GLFWwindow*, int*, int*);
glfwGetWindowSize_func glfwGetWindowSize_impl;
#define glfwGetWindowSize glfwGetWindowSize_impl

typedef void (*glfwSetWindowSizeLimits_func)(GLFWwindow*, int, int, int, int);
glfwSetWindowSizeLimits_func glfwSetWindowSizeLimits_impl;
#define glfwSetWindowSizeLimits glfwSetWindowSizeLimits_impl

typedef void (*glfwSetWindowAspectRatio_func)(GLFWwindow*, int, int);
glfwSetWindowAspectRatio_func glfwSetWindowAspectRatio_impl;
#define glfwSetWindowAspectRatio glfwSetWindowAspectRatio_impl

typedef void (*glfwSetWindowSize_func)(GLFWwindow*, int, int);
glfwSetWindowSize_func glfwSetWindowSize_impl;
#define glfwSetWindowSize glfwSetWindowSize_impl

typedef void (*glfwGetFramebufferSize_func)(GLFWwindow*, int*, int*);
glfwGetFramebufferSize_func glfwGetFramebufferSize_impl;
#define glfwGetFramebufferSize glfwGetFramebufferSize_impl

typedef void (*glfwGetWindowFrameSize_func)(GLFWwindow*, int*, int*, int*, int*);
glfwGetWindowFrameSize_func glfwGetWindowFrameSize_impl;
#define glfwGetWindowFrameSize glfwGetWindowFrameSize_impl

typedef void (*glfwGetWindowContentScale_func)(GLFWwindow*, float*, float*);
glfwGetWindowContentScale_func glfwGetWindowContentScale_impl;
#define glfwGetWindowContentScale glfwGetWindowContentScale_impl

typedef double (*glfwGetDoubleClickInterval_func)(GLFWwindow*);
glfwGetDoubleClickInterval_func glfwGetDoubleClickInterval_impl;
#define glfwGetDoubleClickInterval glfwGetDoubleClickInterval_impl

typedef float (*glfwGetWindowOpacity_func)(GLFWwindow*);
glfwGetWindowOpacity_func glfwGetWindowOpacity_impl;
#define glfwGetWindowOpacity glfwGetWindowOpacity_impl

typedef void (*glfwSetWindowOpacity_func)(GLFWwindow*, float);
glfwSetWindowOpacity_func glfwSetWindowOpacity_impl;
#define glfwSetWindowOpacity glfwSetWindowOpacity_impl

typedef void (*glfwIconifyWindow_func)(GLFWwindow*);
glfwIconifyWindow_func glfwIconifyWindow_impl;
#define glfwIconifyWindow glfwIconifyWindow_impl

typedef void (*glfwRestoreWindow_func)(GLFWwindow*);
glfwRestoreWindow_func glfwRestoreWindow_impl;
#define glfwRestoreWindow glfwRestoreWindow_impl

typedef void (*glfwMaximizeWindow_func)(GLFWwindow*);
glfwMaximizeWindow_func glfwMaximizeWindow_impl;
#define glfwMaximizeWindow glfwMaximizeWindow_impl

typedef void (*glfwShowWindow_func)(GLFWwindow*);
glfwShowWindow_func glfwShowWindow_impl;
#define glfwShowWindow glfwShowWindow_impl

typedef void (*glfwHideWindow_func)(GLFWwindow*);
glfwHideWindow_func glfwHideWindow_impl;
#define glfwHideWindow glfwHideWindow_impl

typedef void (*glfwFocusWindow_func)(GLFWwindow*);
glfwFocusWindow_func glfwFocusWindow_impl;
#define glfwFocusWindow glfwFocusWindow_impl

typedef void (*glfwRequestWindowAttention_func)(GLFWwindow*);
glfwRequestWindowAttention_func glfwRequestWindowAttention_impl;
#define glfwRequestWindowAttention glfwRequestWindowAttention_impl

typedef int (*glfwWindowBell_func)(GLFWwindow*);
glfwWindowBell_func glfwWindowBell_impl;
#define glfwWindowBell glfwWindowBell_impl

typedef GLFWmonitor* (*glfwGetWindowMonitor_func)(GLFWwindow*);
glfwGetWindowMonitor_func glfwGetWindowMonitor_impl;
#define glfwGetWindowMonitor glfwGetWindowMonitor_impl

typedef void (*glfwSetWindowMonitor_func)(GLFWwindow*, GLFWmonitor*, int, int, int, int, int);
glfwSetWindowMonitor_func glfwSetWindowMonitor_impl;
#define glfwSetWindowMonitor glfwSetWindowMonitor_impl

typedef int (*glfwGetWindowAttrib_func)(GLFWwindow*, int);
glfwGetWindowAttrib_func glfwGetWindowAttrib_impl;
#define glfwGetWindowAttrib glfwGetWindowAttrib_impl

typedef void (*glfwSetWindowAttrib_func)(GLFWwindow*, int, int);
glfwSetWindowAttrib_func glfwSetWindowAttrib_impl;
#define glfwSetWindowAttrib glfwSetWindowAttrib_impl

typedef void (*glfwSetWindowUserPointer_func)(GLFWwindow*, void*);
glfwSetWindowUserPointer_func glfwSetWindowUserPointer_impl;
#define glfwSetWindowUserPointer glfwSetWindowUserPointer_impl

typedef void* (*glfwGetWindowUserPointer_func)(GLFWwindow*);
glfwGetWindowUserPointer_func glfwGetWindowUserPointer_impl;
#define glfwGetWindowUserPointer glfwGetWindowUserPointer_impl

typedef GLFWwindowposfun (*glfwSetWindowPosCallback_func)(GLFWwindow*, GLFWwindowposfun);
glfwSetWindowPosCallback_func glfwSetWindowPosCallback_impl;
#define glfwSetWindowPosCallback glfwSetWindowPosCallback_impl

typedef GLFWwindowsizefun (*glfwSetWindowSizeCallback_func)(GLFWwindow*, GLFWwindowsizefun);
glfwSetWindowSizeCallback_func glfwSetWindowSizeCallback_impl;
#define glfwSetWindowSizeCallback glfwSetWindowSizeCallback_impl

typedef GLFWwindowclosefun (*glfwSetWindowCloseCallback_func)(GLFWwindow*, GLFWwindowclosefun);
glfwSetWindowCloseCallback_func glfwSetWindowCloseCallback_impl;
#define glfwSetWindowCloseCallback glfwSetWindowCloseCallback_impl

typedef GLFWwindowrefreshfun (*glfwSetWindowRefreshCallback_func)(GLFWwindow*, GLFWwindowrefreshfun);
glfwSetWindowRefreshCallback_func glfwSetWindowRefreshCallback_impl;
#define glfwSetWindowRefreshCallback glfwSetWindowRefreshCallback_impl

typedef GLFWwindowfocusfun (*glfwSetWindowFocusCallback_func)(GLFWwindow*, GLFWwindowfocusfun);
glfwSetWindowFocusCallback_func glfwSetWindowFocusCallback_impl;
#define glfwSetWindowFocusCallback glfwSetWindowFocusCallback_impl

typedef GLFWwindowocclusionfun (*glfwSetWindowOcclusionCallback_func)(GLFWwindow*, GLFWwindowocclusionfun);
glfwSetWindowOcclusionCallback_func glfwSetWindowOcclusionCallback_impl;
#define glfwSetWindowOcclusionCallback glfwSetWindowOcclusionCallback_impl

typedef GLFWwindowiconifyfun (*glfwSetWindowIconifyCallback_func)(GLFWwindow*, GLFWwindowiconifyfun);
glfwSetWindowIconifyCallback_func glfwSetWindowIconifyCallback_impl;
#define glfwSetWindowIconifyCallback glfwSetWindowIconifyCallback_impl

typedef GLFWwindowmaximizefun (*glfwSetWindowMaximizeCallback_func)(GLFWwindow*, GLFWwindowmaximizefun);
glfwSetWindowMaximizeCallback_func glfwSetWindowMaximizeCallback_impl;
#define glfwSetWindowMaximizeCallback glfwSetWindowMaximizeCallback_impl

typedef GLFWframebuffersizefun (*glfwSetFramebufferSizeCallback_func)(GLFWwindow*, GLFWframebuffersizefun);
glfwSetFramebufferSizeCallback_func glfwSetFramebufferSizeCallback_impl;
#define glfwSetFramebufferSizeCallback glfwSetFramebufferSizeCallback_impl

typedef GLFWwindowcontentscalefun (*glfwSetWindowContentScaleCallback_func)(GLFWwindow*, GLFWwindowcontentscalefun);
glfwSetWindowContentScaleCallback_func glfwSetWindowContentScaleCallback_impl;
#define glfwSetWindowContentScaleCallback glfwSetWindowContentScaleCallback_impl

typedef void (*glfwPostEmptyEvent_func)();
glfwPostEmptyEvent_func glfwPostEmptyEvent_impl;
#define glfwPostEmptyEvent glfwPostEmptyEvent_impl

typedef int (*glfwGetInputMode_func)(GLFWwindow*, int);
glfwGetInputMode_func glfwGetInputMode_impl;
#define glfwGetInputMode glfwGetInputMode_impl

typedef void (*glfwSetInputMode_func)(GLFWwindow*, int, int);
glfwSetInputMode_func glfwSetInputMode_impl;
#define glfwSetInputMode glfwSetInputMode_impl

typedef const char* (*glfwGetKeyName_func)(int, int);
glfwGetKeyName_func glfwGetKeyName_impl;
#define glfwGetKeyName glfwGetKeyName_impl

typedef int (*glfwGetKeyScancode_func)(int);
glfwGetKeyScancode_func glfwGetKeyScancode_impl;
#define glfwGetKeyScancode glfwGetKeyScancode_impl

typedef int (*glfwGetKey_func)(GLFWwindow*, int);
glfwGetKey_func glfwGetKey_impl;
#define glfwGetKey glfwGetKey_impl

typedef int (*glfwGetMouseButton_func)(GLFWwindow*, int);
glfwGetMouseButton_func glfwGetMouseButton_impl;
#define glfwGetMouseButton glfwGetMouseButton_impl

typedef void (*glfwGetCursorPos_func)(GLFWwindow*, double*, double*);
glfwGetCursorPos_func glfwGetCursorPos_impl;
#define glfwGetCursorPos glfwGetCursorPos_impl

typedef void (*glfwSetCursorPos_func)(GLFWwindow*, double, double);
glfwSetCursorPos_func glfwSetCursorPos_impl;
#define glfwSetCursorPos glfwSetCursorPos_impl

typedef GLFWcursor* (*glfwCreateCursor_func)(const GLFWimage*, int, int, int);
glfwCreateCursor_func glfwCreateCursor_impl;
#define glfwCreateCursor glfwCreateCursor_impl

typedef GLFWcursor* (*glfwCreateStandardCursor_func)(GLFWCursorShape);
glfwCreateStandardCursor_func glfwCreateStandardCursor_impl;
#define glfwCreateStandardCursor glfwCreateStandardCursor_impl

typedef void (*glfwDestroyCursor_func)(GLFWcursor*);
glfwDestroyCursor_func glfwDestroyCursor_impl;
#define glfwDestroyCursor glfwDestroyCursor_impl

typedef void (*glfwSetCursor_func)(GLFWwindow*, GLFWcursor*);
glfwSetCursor_func glfwSetCursor_impl;
#define glfwSetCursor glfwSetCursor_impl

typedef GLFWkeyboardfun (*glfwSetKeyboardCallback_func)(GLFWwindow*, GLFWkeyboardfun);
glfwSetKeyboardCallback_func glfwSetKeyboardCallback_impl;
#define glfwSetKeyboardCallback glfwSetKeyboardCallback_impl

typedef void (*glfwUpdateIMEState_func)(GLFWwindow*, int, int, int, int, int);
glfwUpdateIMEState_func glfwUpdateIMEState_impl;
#define glfwUpdateIMEState glfwUpdateIMEState_impl

typedef GLFWmousebuttonfun (*glfwSetMouseButtonCallback_func)(GLFWwindow*, GLFWmousebuttonfun);
glfwSetMouseButtonCallback_func glfwSetMouseButtonCallback_impl;
#define glfwSetMouseButtonCallback glfwSetMouseButtonCallback_impl

typedef GLFWcursorposfun (*glfwSetCursorPosCallback_func)(GLFWwindow*, GLFWcursorposfun);
glfwSetCursorPosCallback_func glfwSetCursorPosCallback_impl;
#define glfwSetCursorPosCallback glfwSetCursorPosCallback_impl

typedef GLFWcursorenterfun (*glfwSetCursorEnterCallback_func)(GLFWwindow*, GLFWcursorenterfun);
glfwSetCursorEnterCallback_func glfwSetCursorEnterCallback_impl;
#define glfwSetCursorEnterCallback glfwSetCursorEnterCallback_impl

typedef GLFWscrollfun (*glfwSetScrollCallback_func)(GLFWwindow*, GLFWscrollfun);
glfwSetScrollCallback_func glfwSetScrollCallback_impl;
#define glfwSetScrollCallback glfwSetScrollCallback_impl

typedef GLFWdropfun (*glfwSetDropCallback_func)(GLFWwindow*, GLFWdropfun);
glfwSetDropCallback_func glfwSetDropCallback_impl;
#define glfwSetDropCallback glfwSetDropCallback_impl

typedef GLFWliveresizefun (*glfwSetLiveResizeCallback_func)(GLFWwindow*, GLFWliveresizefun);
glfwSetLiveResizeCallback_func glfwSetLiveResizeCallback_impl;
#define glfwSetLiveResizeCallback glfwSetLiveResizeCallback_impl

typedef int (*glfwJoystickPresent_func)(int);
glfwJoystickPresent_func glfwJoystickPresent_impl;
#define glfwJoystickPresent glfwJoystickPresent_impl

typedef const float* (*glfwGetJoystickAxes_func)(int, int*);
glfwGetJoystickAxes_func glfwGetJoystickAxes_impl;
#define glfwGetJoystickAxes glfwGetJoystickAxes_impl

typedef const unsigned char* (*glfwGetJoystickButtons_func)(int, int*);
glfwGetJoystickButtons_func glfwGetJoystickButtons_impl;
#define glfwGetJoystickButtons glfwGetJoystickButtons_impl

typedef const unsigned char* (*glfwGetJoystickHats_func)(int, int*);
glfwGetJoystickHats_func glfwGetJoystickHats_impl;
#define glfwGetJoystickHats glfwGetJoystickHats_impl

typedef const char* (*glfwGetJoystickName_func)(int);
glfwGetJoystickName_func glfwGetJoystickName_impl;
#define glfwGetJoystickName glfwGetJoystickName_impl

typedef const char* (*glfwGetJoystickGUID_func)(int);
glfwGetJoystickGUID_func glfwGetJoystickGUID_impl;
#define glfwGetJoystickGUID glfwGetJoystickGUID_impl

typedef void (*glfwSetJoystickUserPointer_func)(int, void*);
glfwSetJoystickUserPointer_func glfwSetJoystickUserPointer_impl;
#define glfwSetJoystickUserPointer glfwSetJoystickUserPointer_impl

typedef void* (*glfwGetJoystickUserPointer_func)(int);
glfwGetJoystickUserPointer_func glfwGetJoystickUserPointer_impl;
#define glfwGetJoystickUserPointer glfwGetJoystickUserPointer_impl

typedef int (*glfwJoystickIsGamepad_func)(int);
glfwJoystickIsGamepad_func glfwJoystickIsGamepad_impl;
#define glfwJoystickIsGamepad glfwJoystickIsGamepad_impl

typedef GLFWjoystickfun (*glfwSetJoystickCallback_func)(GLFWjoystickfun);
glfwSetJoystickCallback_func glfwSetJoystickCallback_impl;
#define glfwSetJoystickCallback glfwSetJoystickCallback_impl

typedef int (*glfwUpdateGamepadMappings_func)(const char*);
glfwUpdateGamepadMappings_func glfwUpdateGamepadMappings_impl;
#define glfwUpdateGamepadMappings glfwUpdateGamepadMappings_impl

typedef const char* (*glfwGetGamepadName_func)(int);
glfwGetGamepadName_func glfwGetGamepadName_impl;
#define glfwGetGamepadName glfwGetGamepadName_impl

typedef int (*glfwGetGamepadState_func)(int, GLFWgamepadstate*);
glfwGetGamepadState_func glfwGetGamepadState_impl;
#define glfwGetGamepadState glfwGetGamepadState_impl

typedef void (*glfwSetClipboardString_func)(GLFWwindow*, const char*);
glfwSetClipboardString_func glfwSetClipboardString_impl;
#define glfwSetClipboardString glfwSetClipboardString_impl

typedef const char* (*glfwGetClipboardString_func)(GLFWwindow*);
glfwGetClipboardString_func glfwGetClipboardString_impl;
#define glfwGetClipboardString glfwGetClipboardString_impl

typedef double (*glfwGetTime_func)();
glfwGetTime_func glfwGetTime_impl;
#define glfwGetTime glfwGetTime_impl

typedef void (*glfwSetTime_func)(double);
glfwSetTime_func glfwSetTime_impl;
#define glfwSetTime glfwSetTime_impl

typedef uint64_t (*glfwGetTimerValue_func)();
glfwGetTimerValue_func glfwGetTimerValue_impl;
#define glfwGetTimerValue glfwGetTimerValue_impl

typedef uint64_t (*glfwGetTimerFrequency_func)();
glfwGetTimerFrequency_func glfwGetTimerFrequency_impl;
#define glfwGetTimerFrequency glfwGetTimerFrequency_impl

typedef void (*glfwMakeContextCurrent_func)(GLFWwindow*);
glfwMakeContextCurrent_func glfwMakeContextCurrent_impl;
#define glfwMakeContextCurrent glfwMakeContextCurrent_impl

typedef GLFWwindow* (*glfwGetCurrentContext_func)();
glfwGetCurrentContext_func glfwGetCurrentContext_impl;
#define glfwGetCurrentContext glfwGetCurrentContext_impl

typedef void (*glfwSwapBuffers_func)(GLFWwindow*);
glfwSwapBuffers_func glfwSwapBuffers_impl;
#define glfwSwapBuffers glfwSwapBuffers_impl

typedef void (*glfwSwapInterval_func)(int);
glfwSwapInterval_func glfwSwapInterval_impl;
#define glfwSwapInterval glfwSwapInterval_impl

typedef int (*glfwExtensionSupported_func)(const char*);
glfwExtensionSupported_func glfwExtensionSupported_impl;
#define glfwExtensionSupported glfwExtensionSupported_impl

typedef GLFWglproc (*glfwGetProcAddress_func)(const char*);
glfwGetProcAddress_func glfwGetProcAddress_impl;
#define glfwGetProcAddress glfwGetProcAddress_impl

typedef int (*glfwVulkanSupported_func)();
glfwVulkanSupported_func glfwVulkanSupported_impl;
#define glfwVulkanSupported glfwVulkanSupported_impl

typedef const char** (*glfwGetRequiredInstanceExtensions_func)(uint32_t*);
glfwGetRequiredInstanceExtensions_func glfwGetRequiredInstanceExtensions_impl;
#define glfwGetRequiredInstanceExtensions glfwGetRequiredInstanceExtensions_impl

typedef void* (*glfwGetCocoaWindow_func)(GLFWwindow*);
glfwGetCocoaWindow_func glfwGetCocoaWindow_impl;
#define glfwGetCocoaWindow glfwGetCocoaWindow_impl

typedef void* (*glfwGetNSGLContext_func)(GLFWwindow*);
glfwGetNSGLContext_func glfwGetNSGLContext_impl;
#define glfwGetNSGLContext glfwGetNSGLContext_impl

typedef uint32_t (*glfwGetCocoaMonitor_func)(GLFWmonitor*);
glfwGetCocoaMonitor_func glfwGetCocoaMonitor_impl;
#define glfwGetCocoaMonitor glfwGetCocoaMonitor_impl

typedef GLFWcocoatextinputfilterfun (*glfwSetCocoaTextInputFilter_func)(GLFWwindow*, GLFWcocoatextinputfilterfun);
glfwSetCocoaTextInputFilter_func glfwSetCocoaTextInputFilter_impl;
#define glfwSetCocoaTextInputFilter glfwSetCocoaTextInputFilter_impl

typedef GLFWcocoatogglefullscreenfun (*glfwSetCocoaToggleFullscreenIntercept_func)(GLFWwindow*, GLFWcocoatogglefullscreenfun);
glfwSetCocoaToggleFullscreenIntercept_func glfwSetCocoaToggleFullscreenIntercept_impl;
#define glfwSetCocoaToggleFullscreenIntercept glfwSetCocoaToggleFullscreenIntercept_impl

typedef GLFWapplicationshouldhandlereopenfun (*glfwSetApplicationShouldHandleReopen_func)(GLFWapplicationshouldhandlereopenfun);
glfwSetApplicationShouldHandleReopen_func glfwSetApplicationShouldHandleReopen_impl;
#define glfwSetApplicationShouldHandleReopen glfwSetApplicationShouldHandleReopen_impl

typedef void (*glfwGetCocoaKeyEquivalent_func)(int, int, void*, void*);
glfwGetCocoaKeyEquivalent_func glfwGetCocoaKeyEquivalent_impl;
#define glfwGetCocoaKeyEquivalent glfwGetCocoaKeyEquivalent_impl

typedef void (*glfwCocoaRequestRenderFrame_func)(GLFWwindow*, GLFWcocoarenderframefun);
glfwCocoaRequestRenderFrame_func glfwCocoaRequestRenderFrame_impl;
#define glfwCocoaRequestRenderFrame glfwCocoaRequestRenderFrame_impl

typedef void* (*glfwGetX11Display_func)();
glfwGetX11Display_func glfwGetX11Display_impl;
#define glfwGetX11Display glfwGetX11Display_impl

typedef int32_t (*glfwGetX11Window_func)(GLFWwindow*);
glfwGetX11Window_func glfwGetX11Window_impl;
#define glfwGetX11Window glfwGetX11Window_impl

typedef void (*glfwSetPrimarySelectionString_func)(GLFWwindow*, const char*);
glfwSetPrimarySelectionString_func glfwSetPrimarySelectionString_impl;
#define glfwSetPrimarySelectionString glfwSetPrimarySelectionString_impl

typedef const char* (*glfwGetPrimarySelectionString_func)(GLFWwindow*);
glfwGetPrimarySelectionString_func glfwGetPrimarySelectionString_impl;
#define glfwGetPrimarySelectionString glfwGetPrimarySelectionString_impl

typedef int (*glfwGetXKBScancode_func)(const char*, int);
glfwGetXKBScancode_func glfwGetXKBScancode_impl;
#define glfwGetXKBScancode glfwGetXKBScancode_impl

typedef void (*glfwRequestWaylandFrameEvent_func)(GLFWwindow*, unsigned long long, GLFWwaylandframecallbackfunc);
glfwRequestWaylandFrameEvent_func glfwRequestWaylandFrameEvent_impl;
#define glfwRequestWaylandFrameEvent glfwRequestWaylandFrameEvent_impl

typedef unsigned long long (*glfwDBusUserNotify_func)(const char*, const char*, const char*, const char*, const char*, int32_t, GLFWDBusnotificationcreatedfun, void*);
glfwDBusUserNotify_func glfwDBusUserNotify_impl;
#define glfwDBusUserNotify glfwDBusUserNotify_impl

typedef void (*glfwDBusSetUserNotificationHandler_func)(GLFWDBusnotificationactivatedfun);
glfwDBusSetUserNotificationHandler_func glfwDBusSetUserNotificationHandler_impl;
#define glfwDBusSetUserNotificationHandler glfwDBusSetUserNotificationHandler_impl

const char* load_glfw(const char* path);
