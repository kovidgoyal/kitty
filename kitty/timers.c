/*
 * timers.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#ifdef __APPLE__
#define EXTRA_INIT mach_timebase_info(&timebase);
#endif
#include "data-types.h"
#include <stdlib.h>
/* To millisecond (10^-3) */
#define SEC_TO_MS 1000

/* To microseconds (10^-6) */
#define MS_TO_US 1000
#define SEC_TO_US (SEC_TO_MS * MS_TO_US)

/* To nanoseconds (10^-9) */
#define US_TO_NS 1000
#define MS_TO_NS (MS_TO_US * US_TO_NS)
#define SEC_TO_NS (SEC_TO_MS * MS_TO_NS)

/* Conversion from nanoseconds */
#define NS_TO_MS (1000 * 1000)
#define NS_TO_US (1000)

#ifdef __APPLE__
#include <mach/mach_time.h>
static mach_timebase_info_data_t timebase = {0};
static inline double monotonic_() {
	return ((double)(mach_absolute_time() * timebase.numer) / timebase.denom)/SEC_TO_NS;
}
#else
#include <time.h>
static inline double monotonic_() {
    struct timespec ts = {0};
#ifdef CLOCK_HIGHRES
	clock_gettime(CLOCK_HIGHRES, &ts);
#elif CLOCK_MONOTONIC_RAW
	clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
	clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
	return (((double)ts.tv_nsec) / SEC_TO_NS) + (double)ts.tv_sec;
}
#endif

double monotonic() { return monotonic_(); }

static PyObject *
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    Timers *self;

    self = (Timers *)type->tp_alloc(type, 0);
    self->capacity = 1024;
    self->count = 0;
    self->buf1 = (TimerEvent*)PyMem_Calloc(2 * self->capacity, sizeof(TimerEvent));
    if (self->buf1 == NULL) { Py_CLEAR(self); return PyErr_NoMemory(); }
    self->events = self->buf1;
    self->buf2 = self->buf1 + self->capacity;
    return (PyObject*) self;
}

static void
dealloc(Timers* self) {
    if (self->events) {
        for (size_t i = 0; i < self->count; i++) {
            Py_CLEAR(self->events[i].callback); Py_CLEAR(self->events[i].args);
        }
        PyMem_Free(self->buf1); self->events = NULL;
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}


static int
compare_events(const void *a, const void *b) {
    double av = ((TimerEvent*)(a))->at, bv = ((TimerEvent*)(b))->at;
    return av > bv ? 1 : (av == bv ? 0 : -1);
}


static inline bool
_add(Timers *self, double at, PyObject *callback, PyObject *args) {
    size_t i; 
    if (self->count >= self->capacity) {
        PyErr_SetString(PyExc_ValueError, "Too many timers");
        return false;
    }
    i = self->count++;
    self->events[i].at = at; self->events[i].callback = callback; self->events[i].args = args;
    Py_INCREF(callback); Py_XINCREF(args);
    qsort(self->events, self->count, sizeof(TimerEvent), compare_events);
    return true;
}

bool
timers_add(Timers *self, double delay, bool update, PyObject *callback, PyObject *args) {
    double at = monotonic_() + delay;

    for (size_t i = 0; i < self->count; i++) {
        if (self->events[i].callback == callback) {
            self->events[i].at = update ? at : MIN(at, self->events[i].at);
            Py_CLEAR(self->events[i].args);
            self->events[i].args = args;
            Py_XINCREF(args);
            qsort(self->events, self->count, sizeof(TimerEvent), compare_events);
            return true;
        }
    }
    return _add(self, at, callback, args);
}


static PyObject *
add(Timers *self, PyObject *fargs) {
#define add_doc "add(delay, callback, args) -> Add callback, replacing it if it already exists"
    PyObject *callback, *args = NULL;
    double delay;
    if (!PyArg_ParseTuple(fargs, "dO|O", &delay, &callback, &args)) return NULL; 
    if (!timers_add(self, delay, true, callback, args)) return NULL;
    Py_RETURN_NONE;
}


bool
timers_add_if_missing(Timers *self, double delay, PyObject *callback, PyObject *args) {
    for (size_t i = 0; i < self->count; i++) {
        if (self->events[i].callback == callback) {
            return true;
        }
    }
    return _add(self, monotonic_() + delay, callback, args); 
}


static PyObject *
add_if_missing(Timers *self, PyObject *fargs) {
#define add_if_missing_doc "add_if_missing(delay, callback, args) -> Add callback, unless it already exists"
    PyObject *callback, *args = NULL;
    double delay;
    if (!PyArg_ParseTuple(fargs, "dO|O", &delay, &callback, &args)) return NULL; 

    if (!timers_add_if_missing(self, delay, callback, args)) return NULL;
    Py_RETURN_NONE;
}

static PyObject *
remove_event(Timers *self, PyObject *callback) {
#define remove_event_doc "remove(callback) -> Remove the event with the specified callback, if present"
    TimerEvent *other = self->events == self->buf1 ? self->buf2 : self->buf1;
    size_t i, j;
    for (i = 0, j = 0; i < self->count; i++) {
        if (self->events[i].callback != callback) {
            other[j].callback = self->events[i].callback; other[j].at = self->events[i].at; other[j].args = self->events[i].args;
            j++;
        } else {
            Py_CLEAR(self->events[i].callback); Py_CLEAR(self->events[i].args);
        }
    }
    self->events = other;
    self->count = j;
    Py_RETURN_NONE;
}

double 
timers_timeout(Timers *self) {
    if (self->count < 1) return -1;
    double ans = self->events[0].at - monotonic_();
    return MAX(0, ans);
}

static PyObject *
timeout(Timers *self) {
#define timeout_doc "timeout() -> The time in seconds until the next event"
    if (self->count < 1) { Py_RETURN_NONE; }
    double ans = self->events[0].at - monotonic_();
    return PyFloat_FromDouble(MAX(0, ans));
}

void
timers_call(Timers *self) {
    if (self->count < 1) return;
    TimerEvent *other = self->events == self->buf1 ? self->buf2 : self->buf1;
    double now = monotonic_();
    size_t i, j;
    for (i = 0, j = 0; i < self->count; i++) {
        if (self->events[i].at <= now) {  // expired, call it
            if (self->events[i].callback != Py_None) {
                PyObject *ret = PyObject_CallObject(self->events[i].callback, self->events[i].args);
                if (ret == NULL) PyErr_Print();
                else Py_DECREF(ret);
            }
            Py_CLEAR(self->events[i].callback); Py_CLEAR(self->events[i].args);
        } else {
            other[j].callback = self->events[i].callback; other[j].at = self->events[i].at; other[j].args = self->events[i].args;
            j++;
        }
    }
    self->events = other;
    self->count = j;
}

static PyObject *
call(Timers *self) {
#define call_doc "call() -> Dispatch all expired events"
    timers_call(self);
    Py_RETURN_NONE;
}

// Boilerplate {{{
static PyMethodDef methods[] = {
    METHOD(add, METH_VARARGS)
    METHOD(add_if_missing, METH_VARARGS)
    METHOD(remove_event, METH_O)
    METHOD(timeout, METH_NOARGS)
    METHOD(call, METH_NOARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject Timers_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Timers",
    .tp_basicsize = sizeof(Timers),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,
    .tp_doc = "Timers",
    .tp_methods = methods,
    .tp_new = new,                
};


INIT_TYPE(Timers)
// }}}
