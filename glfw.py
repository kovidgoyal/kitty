# -*- coding: utf-8 -*-

# -----------------------------------------------------------------------------
#  GLFW - An OpenGL framework
#  API version: 3.0.1
#  WWW:         http://www.glfw.org/
#  ----------------------------------------------------------------------------
#  Copyright (c) 2002-2006 Marcus Geelnard
#  Copyright (c) 2006-2010 Camilla Berglund
#
#  Python bindings - Copyright (c) 2013 Nicolas P. Rougier
#
#  This software is provided 'as-is', without any express or implied
#  warranty. In no event will the authors be held liable for any damages
#  arising from the use of this software.
#
#  Permission is granted to anyone to use this software for any purpose,
#  including commercial applications, and to alter it and redistribute it
#  freely, subject to the following restrictions:
#
#  1. The origin of this software must not be misrepresented; you must not
#     claim that you wrote the original software. If you use this software
#     in a product, an acknowledgment in the product documentation would
#     be appreciated but is not required.
#
#  2. Altered source versions must be plainly marked as such, and must not
#     be misrepresented as being the original software.
#
#  3. This notice may not be removed or altered from any source
#     distribution.
#
# -----------------------------------------------------------------------------

# NOTE:
# This source has been modified from its original form by the vispy dev team

import os
import ctypes.util
from collections import namedtuple
from ctypes import (Structure, POINTER, CFUNCTYPE, byref, c_char_p, c_int,
                    c_uint, c_double, c_float, c_ushort)


_glfw_file = None

# First if there is an environment variable pointing to the library
if 'GLFW_LIBRARY' in os.environ:
    if os.path.exists(os.environ['GLFW_LIBRARY']):
        _glfw_file = os.path.realpath(os.environ['GLFW_LIBRARY'])

# Else, try to find it
if _glfw_file is None:
    order = ['glfw', 'glfw3']
    for check in order:
        _glfw_file = ctypes.util.find_library(check)
        if _glfw_file is not None:
            break

# Else, we failed and exit
if _glfw_file is None:
    raise OSError('GLFW library not found')

# Load it
_glfw = ctypes.CDLL(_glfw_file)


# Ensure it's new enough
def glfwGetVersion():
    major, minor, rev = c_int(0), c_int(0), c_int(0)
    _glfw.glfwGetVersion(byref(major), byref(minor), byref(rev))
    return major.value, minor.value, rev.value

version = glfwGetVersion()

if version[0] != 3:
    version = '.'.join([str(v) for v in version])
    raise OSError('Need GLFW library version 3, found version %s' % version)


# --- Version -----------------------------------------------------------------
GLFW_VERSION_MAJOR = version[0]
GLFW_VERSION_MINOR = version[1]
GLFW_VERSION_REVISION = version[2]
__version__ = GLFW_VERSION_MAJOR, GLFW_VERSION_MINOR, GLFW_VERSION_REVISION

# --- Input handling definitions ----------------------------------------------
GLFW_RELEASE = 0
GLFW_PRESS = 1
GLFW_REPEAT = 2

# --- Keys --------------------------------------------------------------------

# --- The unknown key ---------------------------------------------------------
GLFW_KEY_UNKNOWN = -1

# --- Printable keys ----------------------------------------------------------
GLFW_KEY_SPACE = 32
GLFW_KEY_APOSTROPHE = 39  # ''
GLFW_KEY_COMMA = 44  # ,
GLFW_KEY_MINUS = 45  # -
GLFW_KEY_PERIOD = 46  # .
GLFW_KEY_SLASH = 47  # /
GLFW_KEY_0 = 48
GLFW_KEY_1 = 49
GLFW_KEY_2 = 50
GLFW_KEY_3 = 51
GLFW_KEY_4 = 52
GLFW_KEY_5 = 53
GLFW_KEY_6 = 54
GLFW_KEY_7 = 55
GLFW_KEY_8 = 56
GLFW_KEY_9 = 57
GLFW_KEY_SEMICOLON = 59  # ;
GLFW_KEY_EQUAL = 61  # =
GLFW_KEY_A = 65
GLFW_KEY_B = 66
GLFW_KEY_C = 67
GLFW_KEY_D = 68
GLFW_KEY_E = 69
GLFW_KEY_F = 70
GLFW_KEY_G = 71
GLFW_KEY_H = 72
GLFW_KEY_I = 73
GLFW_KEY_J = 74
GLFW_KEY_K = 75
GLFW_KEY_L = 76
GLFW_KEY_M = 77
GLFW_KEY_N = 78
GLFW_KEY_O = 79
GLFW_KEY_P = 80
GLFW_KEY_Q = 81
GLFW_KEY_R = 82
GLFW_KEY_S = 83
GLFW_KEY_T = 84
GLFW_KEY_U = 85
GLFW_KEY_V = 86
GLFW_KEY_W = 87
GLFW_KEY_X = 88
GLFW_KEY_Y = 89
GLFW_KEY_Z = 90
GLFW_KEY_LEFT_BRACKET = 91  # [
GLFW_KEY_BACKSLASH = 92  # \
GLFW_KEY_RIGHT_BRACKET = 93  # ]
GLFW_KEY_GRAVE_ACCENT = 96  # `
GLFW_KEY_WORLD_1 = 161  # non-US #1
GLFW_KEY_WORLD_2 = 162  # non-US #2

# --- Function keys -----------------------------------------------------------
GLFW_KEY_ESCAPE = 256
GLFW_KEY_ENTER = 257
GLFW_KEY_TAB = 258
GLFW_KEY_BACKSPACE = 259
GLFW_KEY_INSERT = 260
GLFW_KEY_DELETE = 261
GLFW_KEY_RIGHT = 262
GLFW_KEY_LEFT = 263
GLFW_KEY_DOWN = 264
GLFW_KEY_UP = 265
GLFW_KEY_PAGE_UP = 266
GLFW_KEY_PAGE_DOWN = 267
GLFW_KEY_HOME = 268
GLFW_KEY_END = 269
GLFW_KEY_CAPS_LOCK = 280
GLFW_KEY_SCROLL_LOCK = 281
GLFW_KEY_NUM_LOCK = 282
GLFW_KEY_PRINT_SCREEN = 283
GLFW_KEY_PAUSE = 284
GLFW_KEY_F1 = 290
GLFW_KEY_F2 = 291
GLFW_KEY_F3 = 292
GLFW_KEY_F4 = 293
GLFW_KEY_F5 = 294
GLFW_KEY_F6 = 295
GLFW_KEY_F7 = 296
GLFW_KEY_F8 = 297
GLFW_KEY_F9 = 298
GLFW_KEY_F10 = 299
GLFW_KEY_F11 = 300
GLFW_KEY_F12 = 301
GLFW_KEY_F13 = 302
GLFW_KEY_F14 = 303
GLFW_KEY_F15 = 304
GLFW_KEY_F16 = 305
GLFW_KEY_F17 = 306
GLFW_KEY_F18 = 307
GLFW_KEY_F19 = 308
GLFW_KEY_F20 = 309
GLFW_KEY_F21 = 310
GLFW_KEY_F22 = 311
GLFW_KEY_F23 = 312
GLFW_KEY_F24 = 313
GLFW_KEY_F25 = 314
GLFW_KEY_KP_0 = 320
GLFW_KEY_KP_1 = 321
GLFW_KEY_KP_2 = 322
GLFW_KEY_KP_3 = 323
GLFW_KEY_KP_4 = 324
GLFW_KEY_KP_5 = 325
GLFW_KEY_KP_6 = 326
GLFW_KEY_KP_7 = 327
GLFW_KEY_KP_8 = 328
GLFW_KEY_KP_9 = 329
GLFW_KEY_KP_DECIMAL = 330
GLFW_KEY_KP_DIVIDE = 331
GLFW_KEY_KP_MULTIPLY = 332
GLFW_KEY_KP_SUBTRACT = 333
GLFW_KEY_KP_ADD = 334
GLFW_KEY_KP_ENTER = 335
GLFW_KEY_KP_EQUAL = 336
GLFW_KEY_LEFT_SHIFT = 340
GLFW_KEY_LEFT_CONTROL = 341
GLFW_KEY_LEFT_ALT = 342
GLFW_KEY_LEFT_SUPER = 343
GLFW_KEY_RIGHT_SHIFT = 344
GLFW_KEY_RIGHT_CONTROL = 345
GLFW_KEY_RIGHT_ALT = 346
GLFW_KEY_RIGHT_SUPER = 347
GLFW_KEY_MENU = 348
GLFW_KEY_LAST = GLFW_KEY_MENU


# --- Modifiers ---------------------------------------------------------------
GLFW_MOD_SHIFT = 0x0001
GLFW_MOD_CONTROL = 0x0002
GLFW_MOD_ALT = 0x0004
GLFW_MOD_SUPER = 0x0008

# --- Mouse -------------------------------------------------------------------
GLFW_MOUSE_BUTTON_1 = 0
GLFW_MOUSE_BUTTON_2 = 1
GLFW_MOUSE_BUTTON_3 = 2
GLFW_MOUSE_BUTTON_4 = 3
GLFW_MOUSE_BUTTON_5 = 4
GLFW_MOUSE_BUTTON_6 = 5
GLFW_MOUSE_BUTTON_7 = 6
GLFW_MOUSE_BUTTON_8 = 7
GLFW_MOUSE_BUTTON_LAST = GLFW_MOUSE_BUTTON_8
GLFW_MOUSE_BUTTON_LEFT = GLFW_MOUSE_BUTTON_1
GLFW_MOUSE_BUTTON_RIGHT = GLFW_MOUSE_BUTTON_2
GLFW_MOUSE_BUTTON_MIDDLE = GLFW_MOUSE_BUTTON_3


# --- Joystick ----------------------------------------------------------------
GLFW_JOYSTICK_1 = 0
GLFW_JOYSTICK_2 = 1
GLFW_JOYSTICK_3 = 2
GLFW_JOYSTICK_4 = 3
GLFW_JOYSTICK_5 = 4
GLFW_JOYSTICK_6 = 5
GLFW_JOYSTICK_7 = 6
GLFW_JOYSTICK_8 = 7
GLFW_JOYSTICK_9 = 8
GLFW_JOYSTICK_10 = 9
GLFW_JOYSTICK_11 = 10
GLFW_JOYSTICK_12 = 11
GLFW_JOYSTICK_13 = 12
GLFW_JOYSTICK_14 = 13
GLFW_JOYSTICK_15 = 14
GLFW_JOYSTICK_16 = 15
GLFW_JOYSTICK_LAST = GLFW_JOYSTICK_16


# --- Error codes -------------------------------------------------------------
GLFW_NOT_INITIALIZED = 0x00010001
GLFW_NO_CURRENT_CONTEXT = 0x00010002
GLFW_INVALID_ENUM = 0x00010003
GLFW_INVALID_VALUE = 0x00010004
GLFW_OUT_OF_MEMORY = 0x00010005
GLFW_API_UNAVAILABLE = 0x00010006
GLFW_VERSION_UNAVAILABLE = 0x00010007
GLFW_PLATFORM_ERROR = 0x00010008
GLFW_FORMAT_UNAVAILABLE = 0x00010009

# ---
GLFW_FOCUSED = 0x00020001
GLFW_ICONIFIED = 0x00020002
GLFW_RESIZABLE = 0x00020003
GLFW_VISIBLE = 0x00020004
GLFW_DECORATED = 0x00020005
GLFW_AUTO_ICONIFY = 0x00020006
GLFW_FLOATING = 0x00020007

# ---
GLFW_RED_BITS = 0x00021001
GLFW_GREEN_BITS = 0x00021002
GLFW_BLUE_BITS = 0x00021003
GLFW_ALPHA_BITS = 0x00021004
GLFW_DEPTH_BITS = 0x00021005
GLFW_STENCIL_BITS = 0x00021006
GLFW_ACCUM_RED_BITS = 0x00021007
GLFW_ACCUM_GREEN_BITS = 0x00021008
GLFW_ACCUM_BLUE_BITS = 0x00021009
GLFW_ACCUM_ALPHA_BITS = 0x0002100A
GLFW_AUX_BUFFERS = 0x0002100B
GLFW_STEREO = 0x0002100C
GLFW_SAMPLES = 0x0002100D
GLFW_SRGB_CAPABLE = 0x0002100E
GLFW_REFRESH_RATE = 0x0002100F
GLFW_DOUBLEBUFFER = 0x00021010

# ---
GLFW_CLIENT_API = 0x00022001
GLFW_CONTEXT_VERSION_MAJOR = 0x00022002
GLFW_CONTEXT_VERSION_MINOR = 0x00022003
GLFW_CONTEXT_REVISION = 0x00022004
GLFW_CONTEXT_ROBUSTNESS = 0x00022005
GLFW_OPENGL_FORWARD_COMPAT = 0x00022006
GLFW_OPENGL_DEBUG_CONTEXT = 0x00022007
GLFW_OPENGL_PROFILE = 0x00022008

# ---
GLFW_OPENGL_API = 0x00030001
GLFW_OPENGL_ES_API = 0x00030002

# ---
GLFW_NO_ROBUSTNESS = 0
GLFW_NO_RESET_NOTIFICATION = 0x00031001
GLFW_LOSE_CONTEXT_ON_RESET = 0x00031002

# ---
GLFW_OPENGL_ANY_PROFILE = 0
GLFW_OPENGL_CORE_PROFILE = 0x00032001
GLFW_OPENGL_COMPAT_PROFILE = 0x00032002

# ---
GLFW_CURSOR = 0x00033001
GLFW_STICKY_KEYS = 0x00033002
GLFW_STICKY_MOUSE_BUTTONS = 0x00033003

# ---
GLFW_CURSOR_NORMAL = 0x00034001
GLFW_CURSOR_HIDDEN = 0x00034002
GLFW_CURSOR_DISABLED = 0x00034003

# ---
GLFW_CONNECTED = 0x00040001
GLFW_DISCONNECTED = 0x00040002


# --- Structures --------------------------------------------------------------
class GLFWvidmode(Structure):
    _fields_ = [('width',       c_int),
                ('height',      c_int),
                ('redBits',     c_int),
                ('greenBits',   c_int),
                ('blueBits',    c_int),
                ('refreshRate', c_int)]


class GLFWgammaramp(Structure):
    _fields_ = [('red',     POINTER(c_ushort)),
                ('green',   POINTER(c_ushort)),
                ('blue',    POINTER(c_ushort)),
                ('size',    c_int)]


class GLFWwindow(Structure):
    pass


class GLFWmonitor(Structure):
    pass

# --- Callbacks ---------------------------------------------------------------
errorfun = CFUNCTYPE(None, c_int, c_char_p)
windowposfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int, c_int)
windowsizefun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int, c_int)
windowclosefun = CFUNCTYPE(None, POINTER(GLFWwindow))
windowrefreshfun = CFUNCTYPE(None, POINTER(GLFWwindow))
windowfocusfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int)
windowiconifyfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int)
framebuffersizefun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int, c_int)
mousebuttonfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int, c_int, c_int)
cursorposfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_double, c_double)
cursorenterfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int)
scrollfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_double, c_double)
keyfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_int, c_int, c_int, c_int)
charfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_uint)
monitorfun = CFUNCTYPE(None, POINTER(GLFWmonitor), c_int)

# --- Init --------------------------------------------------------------------
glfwInit = _glfw.glfwInit
glfwTerminate = _glfw.glfwTerminate
# glfwGetVersion                 = _glfw.glfwGetVersion

# --- Error -------------------------------------------------------------------
# glfwSetErrorCallback            = _glfw.glfwSetErrorCallback

# --- Monitor -----------------------------------------------------------------
# glfwGetMonitors                 = _glfw.glfwGetMonitors
# glfwGetMonitors.restype         = POINTER(GLFWmonitor)
glfwGetPrimaryMonitor = _glfw.glfwGetPrimaryMonitor
glfwGetPrimaryMonitor.restype = POINTER(GLFWmonitor)
# glfwGetMonitorPos               = _glfw.glfwGetMonitorPos
# glfwGetMonitorPhysicalSize      = _glfw.glfwGetMonitorPhysicalSize
glfwGetMonitorName = _glfw.glfwGetMonitorName
glfwGetMonitorName.restype = c_char_p
# glfwSetMonitorCallback          = _glfw.glfwSetMonitorCallback
# glfwGetVideoModes               = _glfw.glfwGetVideoModes
# glfwGetVideoMode                = _glfw.glfwGetVideoMode

# --- Gama --------------------------------------------------------------------
glfwSetGamma = _glfw.glfwSetGamma
# glfwGetGammaRamp               = _glfw.glfwGetGammaRamp
# glfwSetGammaRamp               = _glfw.glfwSetGammaRamp

# --- Window ------------------------------------------------------------------
glfwDefaultWindowHints = _glfw.glfwDefaultWindowHints
glfwWindowHint = _glfw.glfwWindowHint
# glfwCreateWindow              = _glfw.glfwCreateWindow
# glfwDestroyWindow              = _glfw.glfwDestroyWindow
glfwWindowShouldClose = _glfw.glfwWindowShouldClose
glfwSetWindowShouldClose = _glfw.glfwSetWindowShouldClose
glfwSetWindowTitle = _glfw.glfwSetWindowTitle
# glfwGetWindowPos              = _glfw.glfwGetWindowPos
glfwSetWindowPos = _glfw.glfwSetWindowPos
# glfwGetWindowSize             = _glfw.glfwGetWindowSize
glfwSetWindowSize = _glfw.glfwSetWindowSize
# glfwGetFramebufferSize        = _glfw.glfwGetFramebufferSize
glfwIconifyWindow = _glfw.glfwIconifyWindow
glfwRestoreWindow = _glfw.glfwRestoreWindow
glfwShowWindow = _glfw.glfwShowWindow
glfwHideWindow = _glfw.glfwHideWindow
glfwGetWindowMonitor = _glfw.glfwGetWindowMonitor
glfwGetWindowAttrib = _glfw.glfwGetWindowAttrib
glfwSetWindowUserPointer = _glfw.glfwSetWindowUserPointer
glfwGetWindowUserPointer = _glfw.glfwGetWindowUserPointer
# glfwSetWindowPosCallback       = _glfw.glfwSetWindowPosCallback
# glfwSetWindowSizeCallback      = _glfw.glfwSetWindowSizeCallback
# glfwSetWindowCloseCallback     = _glfw.glfwSetWindowCloseCallback
# glfwSetWindowRefreshCallback   = _glfw.glfwSetWindowRefreshCallback
# glfwSetWindowFocusCallback     = _glfw.glfwSetWindowFocusCallback
# glfwSetWindowIconifyCallback   = _glfw.glfwSetWindowIconifyCallback
# glfwSetFramebufferSizeCallback = _glfw.glfwSetFramebufferSizeCallback
glfwPollEvents = _glfw.glfwPollEvents
glfwWaitEvents = _glfw.glfwWaitEvents
glfwPostEmptyEvent = _glfw.glfwPostEmptyEvent

# --- Input -------------------------------------------------------------------
glfwGetInputMode = _glfw.glfwGetInputMode
glfwSetInputMode = _glfw.glfwSetInputMode
glfwGetKey = _glfw.glfwGetKey
glfwGetMouseButton = _glfw.glfwGetMouseButton
# glfwGetCursorPos               = _glfw.glfwGetCursorPos
glfwSetCursorPos = _glfw.glfwSetCursorPos
# glfwSetKeyCallback             = _glfw.glfwSetKeyCallback
# glfwSetCharCallback            = _glfw.glfwSetCharCallback
# glfwSetMouseButtonCallback     = _glfw.glfwSetMouseButtonCallback
# glfwSetCursorPosCallback       = _glfw.glfwSetCursorPosCallback
# glfwSetCursorEnterCallback     = _glfw.glfwSetCursorEnterCallback
# glfwSetScrollCallback          = _glfw.glfwSetScrollCallback
glfwJoystickPresent = _glfw.glfwJoystickPresent
# glfwGetJoystickAxes            = _glfw.glfwGetJoystickAxes
# glfwGetJoystickButtons         = _glfw.glfwGetJoystickButtons
glfwGetJoystickName = _glfw.glfwGetJoystickName
glfwGetJoystickName.restype = c_char_p

# --- Clipboard ---------------------------------------------------------------
glfwSetClipboardString = _glfw.glfwSetClipboardString
glfwGetClipboardString = _glfw.glfwGetClipboardString
glfwGetClipboardString.restype = c_char_p

# --- Timer -------------------------------------------------------------------
glfwGetTime = _glfw.glfwGetTime
glfwGetTime.restype = c_double
glfwSetTime = _glfw.glfwSetTime

# --- Context -----------------------------------------------------------------
glfwMakeContextCurrent = _glfw.glfwMakeContextCurrent
glfwGetCurrentContext = _glfw.glfwGetCurrentContext
glfwSwapBuffers = _glfw.glfwSwapBuffers
glfwSwapInterval = _glfw.glfwSwapInterval
glfwExtensionSupported = _glfw.glfwExtensionSupported
glfwGetProcAddress = _glfw.glfwGetProcAddress


# --- Pythonizer --------------------------------------------------------------

# This keeps track of current windows
__windows__ = []
__destroyed__ = []

# This is to prevent garbage collection on callbacks
__c_callbacks__ = {}
__py_callbacks__ = {}
__c_error_callback__ = None


def glfwCreateWindow(width=640, height=480, title="GLFW Window",
                     monitor=None, share=None):
    _glfw.glfwCreateWindow.restype = POINTER(GLFWwindow)
    window = _glfw.glfwCreateWindow(width, height, title, monitor, share)
    __windows__.append(window)
    __destroyed__.append(False)
    index = __windows__.index(window)
    __c_callbacks__[index] = {}
    __py_callbacks__[index] = {'errorfun': None,
                               'monitorfun': None,
                               'windowposfun': None,
                               'windowsizefun': None,
                               'windowclosefun': None,
                               'windowrefreshfun': None,
                               'windowfocusfun': None,
                               'windowiconifyfun': None,
                               'framebuffersizefun': None,
                               'keyfun': None,
                               'charfun': None,
                               'mousebuttonfun': None,
                               'cursorposfun': None,
                               'cursorenterfun': None,
                               'scrollfun': None}
    return window


def glfwDestroyWindow(window):
    index = __windows__.index(window)
    if not __destroyed__[index]:
        _glfw.glfwDestroyWindow(window)
        # We do not delete window from the list (or it would impact numbering)
        del __c_callbacks__[index]
        del __py_callbacks__[index]
        # del __windows__[index]
    __destroyed__[index] = True


def glfwGetWindowPos(window):
    xpos, ypos = c_int(0), c_int(0)
    _glfw.glfwGetWindowPos(window, byref(xpos), byref(ypos))
    return xpos.value, ypos.value


def glfwGetCursorPos(window):
    xpos, ypos = c_double(0), c_double(0)
    _glfw.glfwGetCursorPos(window, byref(xpos), byref(ypos))
    return int(xpos.value), int(ypos.value)


def glfwGetWindowSize(window):
    width, height = c_int(0), c_int(0)
    _glfw.glfwGetWindowSize(window, byref(width), byref(height))
    return width.value, height.value


def glfwGetFramebufferSize(window):
    width, height = c_int(0), c_int(0)
    _glfw.glfwGetFramebufferSize(window, byref(width), byref(height))
    return width.value, height.value


def glfwGetMonitors():
    count = c_int(0)
    _glfw.glfwGetMonitors.restype = POINTER(POINTER(GLFWmonitor))
    c_monitors = _glfw.glfwGetMonitors(byref(count))
    return [c_monitors[i] for i in range(count.value)]


def glfwGetVideoModes(monitor):
    count = c_int(0)
    _glfw.glfwGetVideoModes.restype = POINTER(GLFWvidmode)
    c_modes = _glfw.glfwGetVideoModes(monitor, byref(count))
    modes = []
    for i in range(count.value):
        modes.append((c_modes[i].width,
                      c_modes[i].height,
                      c_modes[i].redBits,
                      c_modes[i].blueBits,
                      c_modes[i].greenBits,
                      c_modes[i].refreshRate))
    return modes


def glfwGetMonitorPos(monitor):
    xpos, ypos = c_int(0), c_int(0)
    _glfw.glfwGetMonitorPos(monitor, byref(xpos), byref(ypos))
    return xpos.value, ypos.value


def glfwGetMonitorPhysicalSize(monitor):
    width, height = c_int(0), c_int(0)
    _glfw.glfwGetMonitorPhysicalSize(monitor, byref(width), byref(height))
    return width.value, height.value


VideoMode = namedtuple('VideoMode', 'width height redBits blueBits greenBits refreshRate')


def glfwGetVideoMode(monitor):
    _glfw.glfwGetVideoMode.restype = POINTER(GLFWvidmode)
    c_mode = _glfw.glfwGetVideoMode(monitor).contents
    return VideoMode(
        c_mode.width, c_mode.height, c_mode.redBits, c_mode.blueBits, c_mode.greenBits, c_mode.refreshRate)


def GetGammaRamp(monitor):
    _glfw.glfwGetGammaRamp.restype = POINTER(GLFWgammaramp)
    c_gamma = _glfw.glfwGetGammaRamp(monitor).contents
    gamma = {'red': [], 'green': [], 'blue': []}
    if c_gamma:
        for i in range(c_gamma.size):
            gamma['red'].append(c_gamma.red[i])
            gamma['green'].append(c_gamma.green[i])
            gamma['blue'].append(c_gamma.blue[i])
    return gamma


def glfwGetJoystickAxes(joy):
    count = c_int(0)
    _glfw.glfwGetJoystickAxes.restype = POINTER(c_float)
    c_axes = _glfw.glfwGetJoystickAxes(joy, byref(count))
    axes = [c_axes[i].value for i in range(count)]
    return axes


def glfwGetJoystickButtons(joy):
    count = c_int(0)
    _glfw.glfwGetJoystickButtons.restype = POINTER(c_int)
    c_buttons = _glfw.glfwGetJoystickButtons(joy, byref(count))
    buttons = [c_buttons[i].value for i in range(count)]
    return buttons


# --- Callbacks ---------------------------------------------------------------

def __callback__(name):
    callback = 'glfwSet%sCallback' % name
    fun = '%sfun' % name.lower()
    code = """
def %(callback)s(window, callback = None):
    index = __windows__.index(window)
    old_callback = __py_callbacks__[index]['%(fun)s']
    __py_callbacks__[index]['%(fun)s'] = callback
    if callback: callback = %(fun)s(callback)
    __c_callbacks__[index]['%(fun)s'] = callback
    _glfw.%(callback)s(window, callback)
    return old_callback""" % {'callback': callback, 'fun': fun}
    return code

exec(__callback__('Monitor'))
exec(__callback__('WindowPos'))
exec(__callback__('WindowSize'))
exec(__callback__('WindowClose'))
exec(__callback__('WindowRefresh'))
exec(__callback__('WindowFocus'))
exec(__callback__('WindowIconify'))
exec(__callback__('FramebufferSize'))
exec(__callback__('Key'))
exec(__callback__('Char'))
exec(__callback__('MouseButton'))
exec(__callback__('CursorPos'))
exec(__callback__('Scroll'))


# Error callback does not take window parameter
def glfwSetErrorCallback(callback=None):
    global __c_error_callback__
    __c_error_callback__ = errorfun(callback)
    _glfw.glfwSetErrorCallback(__c_error_callback__)
