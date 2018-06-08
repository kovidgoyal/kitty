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
#include <unistd.h>
#include <poll.h>
#include <errno.h>

#ifdef __NetBSD__
#define ppoll pollts
#endif

static inline void
drainFd(int fd) {
    static char drain_buf[64];
    while(read(fd, drain_buf, sizeof(drain_buf)) < 0 && errno == EINTR);
}


static inline int
pollWithTimeout(struct pollfd *fds, nfds_t nfds, double timeout) {
    const long seconds = (long) timeout;
    const long nanoseconds = (long) ((timeout - seconds) * 1e9);
    struct timespec tv = { seconds, nanoseconds };
    return ppoll(fds, nfds, &tv, NULL);
}

static inline void
initPollData(struct pollfd *fds, int wakeup_fd, int display_fd) {
    fds[0].fd = wakeup_fd; fds[1].fd = display_fd;
    fds[0].events = POLLIN; fds[1].events = POLLIN;
}

static inline void
closeFds(int *fds, size_t count) {
    while(count--) {
        if (*fds > 0) {
            close(*fds);
            *fds = -1;
        }
        fds++;
    }
}
