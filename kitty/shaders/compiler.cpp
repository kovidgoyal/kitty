/*
 * compiler.cpp
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <Python.h>
#if __has_include("shader-slang/slang.h")
#include <shader-slang/slang.h>
#include <shader-slang/slang-com-ptr.h>
#include <shader-slang/slang-com-helper.h>
#else
#include <slang.h>
#include <slang-com-ptr.h>
#include <slang-com-helper.h>
#endif

using namespace slang;

class ScopedPyObject {  // {{{
private:
    PyObject* ptr;

public:
    // Default constructor
    ScopedPyObject() : ptr(nullptr) {}

    // Constructor that takes ownership of a PyObject*
    // Set 'is_strong_ref' to false if you are passing a borrowed reference
    explicit ScopedPyObject(PyObject* p, bool is_strong_ref = true) : ptr(p) {
        if (!is_strong_ref && ptr) {
            Py_INCREF(ptr);
        }
    }

    // Destructor automatically decrements the reference count
    ~ScopedPyObject() {
        Py_XDECREF(ptr);
    }

    // Delete copy operations to prevent accidental double-decref
    ScopedPyObject(const ScopedPyObject&) = delete;
    ScopedPyObject& operator=(const ScopedPyObject&) = delete;

    // Move constructor transfers ownership
    ScopedPyObject(ScopedPyObject&& other) noexcept : ptr(other.ptr) {
        other.ptr = nullptr;
    }

    // Move assignment operator
    ScopedPyObject& operator=(ScopedPyObject&& other) noexcept {
        if (this != &other) {
            Py_XDECREF(ptr);
            ptr = other.ptr;
            other.ptr = nullptr;
        }
        return *this;
    }

    // Allow assignment directly from a raw PyObject* (assumes strong reference)
    ScopedPyObject& operator=(PyObject* p) {
        Py_XDECREF(ptr);
        ptr = p;
        return *this;
    }

    // Smart pointer operators
    PyObject* get() const { return ptr; }
    PyObject* operator->() const { return ptr; }
    explicit operator bool() const { return ptr != nullptr; }

    // Release ownership without changing the ref count (returns raw pointer)
    PyObject* release() {
        PyObject* temp = ptr;
        ptr = nullptr;
        return temp;
    }

    // Safely reset to a new raw pointer
    void reset(PyObject* p = nullptr, bool is_strong_ref = true) {
        Py_XDECREF(ptr);
        ptr = p;
        if (!is_strong_ref && ptr) {
            Py_INCREF(ptr);
        }
    }
}; // }}}

typedef struct GlobalSession {
    PyObject_HEAD

    Slang::ComPtr<IGlobalSession> ptr;
} GlobalSession;

static std::string
get_slang_result_string(SlangResult result) {
    switch (result) {
        case SLANG_OK: return "SLANG_OK: Operation succeeded.";
        case SLANG_FAIL: return "SLANG_FAIL: Generic operational failure.";
        case SLANG_E_NOT_AVAILABLE: return "SLANG_E_NOT_AVAILABLE: The requested feature or interface is not available.";
        case SLANG_E_NOT_IMPLEMENTED: return "SLANG_E_NOT_IMPLEMENTED: The feature has not been implemented.";
        case SLANG_E_INVALID_ARG: return "SLANG_E_INVALID_ARG: One or more arguments are invalid.";
        case SLANG_E_OUT_OF_MEMORY: return "SLANG_E_OUT_OF_MEMORY: The compiler ran out of memory.";
        case SLANG_E_BUFFER_TOO_SMALL: return "SLANG_E_BUFFER_TOO_SMALL: The destination buffer is too small to hold the data.";
        case SLANG_E_UNINITIALIZED: return "SLANG_E_UNINITIALIZED: A component or object was used without initialization.";
        case SLANG_E_TIME_OUT: return "SLANG_E_TIME_OUT: The compilation or operation timed out.";
        // Internal status codes often returned by compile steps
        default:
            if (result < 0) return "SLANG_ERROR_UNKNOWN: Code (0x" + std::to_string(result) + ")";
            return "SLANG_STATUS_UNKNOWN: Code (0x" + std::to_string(result) + ")";
    }
}

static PyObject *Error = nullptr;

static void
set_python_error(SlangResult r, const char *msg, PyObject *exc_class = nullptr) {
    if (exc_class == nullptr) exc_class = Error;
    PyErr_Format(exc_class, "%s: %s", msg, get_slang_result_string(r).c_str());
}

static PyObject*
new_gs(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    GlobalSession *self;
    static const char* kw[] = {"enable_glsl_input", NULL};
    int enable_glsl_input = 0;
    if (args && !PyArg_ParseTupleAndKeywords(args, kwds, "|p", kw, &enable_glsl_input)) return NULL;
    self = (GlobalSession *)type->tp_alloc(type, 0);
    ScopedPyObject ans((PyObject*)self);
    if (self != NULL) {
        self->ptr = nullptr;
        SlangGlobalSessionDesc desc = {.enableGLSL=static_cast<bool>(enable_glsl_input)};
        SlangResult result = createGlobalSession(&desc, self->ptr.writeRef());
        if (SLANG_FAILED(result)) {
            set_python_error(result, "failed to create slang global session");
            ans.reset();
        }
    }
    return ans.release();
}

static void
dealloc_gs(GlobalSession* self) {
    self->ptr = nullptr;
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyMethodDef gs_methods[] = {
    {NULL}  /* Sentinel */
};


PyTypeObject GlobalSession_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
};

static char doc[] = "Compile shaders";
static PyMethodDef methods[] = {
    {NULL}  /* Sentinel */
};

static int
exec_module(PyObject *mod) {
    Error = PyErr_NewException("slangc.Error", NULL, NULL);
    if (Error == nullptr) return -1;
    GlobalSession_Type.tp_name = "slangc.GlobalSession";
    GlobalSession_Type.tp_basicsize = sizeof(GlobalSession);
    GlobalSession_Type.tp_dealloc = (destructor)dealloc_gs;
    GlobalSession_Type.tp_flags = Py_TPFLAGS_DEFAULT;
    GlobalSession_Type.tp_doc = "GlobalSession";
    GlobalSession_Type.tp_methods = gs_methods;
    GlobalSession_Type.tp_new = new_gs;
    if (PyType_Ready(&GlobalSession_Type) < 0) { return -1; }
    if (PyModule_AddObject(mod, "GlobalSession", (PyObject *)&GlobalSession_Type) != 0) return -1;
    Py_INCREF(&GlobalSession_Type);
    if (PyModule_AddObject(mod, "Error", Error) < 0) { return -1; }
    Py_INCREF(Error);
    return 0;
}

static PyModuleDef_Slot slots[] = { {Py_mod_exec, (void*)exec_module}, {0, NULL} };

static struct PyModuleDef module_def = {PyModuleDef_HEAD_INIT};

PyMODINIT_FUNC
PyInit_slangc(void) {
	module_def.m_name = "slangc";
	module_def.m_slots = slots;
	module_def.m_doc = doc;
	module_def.m_methods = methods;
	return PyModuleDef_Init(&module_def);
}
