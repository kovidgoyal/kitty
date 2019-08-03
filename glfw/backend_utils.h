//========================================================================
// GLFW 3.4 Wayland - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2014 Jonas Ådahl <jadahl@gmail.com>
//
// This software is provided 'as-is', without any express or implied
// warranty. In no event will the authors be held liable for any damages
// arising from the use of this software.
//
// Permission is granted to anyone to use this software for any purpose,
// including commercial applications, and to alter it and redistribute it
// freely, subject to the following restrictions:
//
// 1. The origin of this software must not be misrepresented; you must not
//    claim that you wrote the original software. If you use this software
//    in a product, an acknowledgment in the product documentation would
//    be appreciated but is not required.
//
// 2. Altered source versions must be plainly marked as such, and must not
//    be misrepresented as being the original software.
//
// 3. This notice may not be removed or altered from any source
//    distribution.
//
//========================================================================

#pragma once
#include <poll.h>
#include <unistd.h>
#include <stdbool.h>

#ifdef __has_include
#if __has_include(<sys/eventfd.h>)
#define HAS_EVENT_FD
#include <sys/eventfd.h>
#endif
#else
#define HAS_EVENT_FD
#include <sys/eventfd.h>
#endif

typedef unsigned long long id_type;
typedef void(*watch_callback_func)(int, int, void*);
typedef void(*timer_callback_func)(id_type, void*);
typedef void (* GLFWuserdatafreefun)(id_type, void*);

typedef struct {
    int fd, events, enabled, ready;
    watch_callback_func callback;
    void *callback_data;
    GLFWuserdatafreefun free;
    id_type id;
    const char *name;
} Watch;

typedef struct {
    id_type id;
    double interval, trigger_at;
    timer_callback_func callback;
    void *callback_data;
    GLFWuserdatafreefun free;
    const char *name;
    bool repeats;
} Timer;


typedef struct {
    struct pollfd fds[32];
#ifdef HAS_EVENT_FD
    int wakeupFd;
#else
    int wakeupFds[2];
#endif
    bool wakeup_data_read, wakeup_fd_ready;
    nfds_t watches_count, timers_count;
    Watch watches[32];
    Timer timers[128];
} EventLoopData;


void check_for_wakeup_events(EventLoopData *eld);
id_type addWatch(EventLoopData *eld, const char *name, int fd, int events, int enabled, watch_callback_func cb, void *cb_data);
void removeWatch(EventLoopData *eld, id_type watch_id);
void toggleWatch(EventLoopData *eld, id_type watch_id, int enabled);
id_type addTimer(EventLoopData *eld, const char *name, double interval, int enabled, bool repeats, timer_callback_func cb, void *cb_data, GLFWuserdatafreefun free);
void removeTimer(EventLoopData *eld, id_type timer_id);
void removeAllTimers(EventLoopData *eld);
void toggleTimer(EventLoopData *eld, id_type timer_id, int enabled);
void changeTimerInterval(EventLoopData *eld, id_type timer_id, double interval);
double prepareForPoll(EventLoopData *eld, double timeout);
int pollWithTimeout(struct pollfd *fds, nfds_t nfds, double timeout);
int pollForEvents(EventLoopData *eld, double timeout);
unsigned dispatchTimers(EventLoopData *eld);
void finalizePollData(EventLoopData *eld);
bool initPollData(EventLoopData *eld, int display_fd);
char** parseUriList(char* text, int* count);
void wakeupEventLoop(EventLoopData *eld);
