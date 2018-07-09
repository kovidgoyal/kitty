//========================================================================
// GLFW 3.3 Wayland - www.glfw.org
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

typedef void(*watch_callback_func)(int, int, void*);
typedef unsigned long long id_type;

typedef struct {
    int fd, events, enabled, ready;
    watch_callback_func callback;
    void *callback_data;
    id_type id;
} Watch;

typedef struct {
    struct pollfd fds[32];
    int wakeupFds[2];
    nfds_t watches_count, fds_count;
    Watch watches[32];
} EventLoopData;


id_type addWatch(EventLoopData *eld, int fd, int events, int enabled, watch_callback_func cb, void *cb_data);
void removeWatch(EventLoopData *eld, id_type watch_id);
void toggleWatch(EventLoopData *eld, id_type watch_id, int enabled);
void prepareForPoll(EventLoopData *eld);
int pollWithTimeout(struct pollfd *fds, nfds_t nfds, double timeout);
void dispatchEvents(EventLoopData *eld);
void closeFds(int *fds, size_t count);
void initPollData(EventLoopData *eld, int wakeup_fd, int display_fd);
