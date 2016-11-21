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
charmodsfun = CFUNCTYPE(None, POINTER(GLFWwindow), c_uint, c_int)
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
                               'charmodsfun': None,
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
exec(__callback__('CharMods'))
exec(__callback__('MouseButton'))
exec(__callback__('CursorPos'))
exec(__callback__('Scroll'))


# Error callback does not take window parameter
def glfwSetErrorCallback(callback=None):
    global __c_error_callback__
    __c_error_callback__ = errorfun(callback)
    _glfw.glfwSetErrorCallback(__c_error_callback__)
