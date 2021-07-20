/*
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#ifdef HAS_MEMFD_CREATE

#include <unistd.h>
#include <sys/syscall.h>
static inline int glfw_memfd_create(const char *name, unsigned int flags) {
    return (int)syscall(__NR_memfd_create, name, flags);
}

#ifndef F_LINUX_SPECIFIC_BASE
#define F_LINUX_SPECIFIC_BASE 1024
#endif

#ifndef F_ADD_SEALS
#define F_ADD_SEALS (F_LINUX_SPECIFIC_BASE + 9)
#define F_GET_SEALS (F_LINUX_SPECIFIC_BASE + 10)

#define F_SEAL_SEAL     0x0001  /* prevent further seals from being set */
#define F_SEAL_SHRINK   0x0002  /* prevent file from shrinking */
#define F_SEAL_GROW     0x0004  /* prevent file from growing */
#define F_SEAL_WRITE    0x0008  /* prevent writes */
#endif

#ifndef MFD_CLOEXEC
#define MFD_CLOEXEC     0x0001U
#define MFD_ALLOW_SEALING 0x0002U
#endif

#else

#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>

static inline int createTmpfileCloexec(char* tmpname)
{
    int fd;

    fd = mkostemp(tmpname, O_CLOEXEC);
    if (fd >= 0)
        unlink(tmpname);

    return fd;
}

#endif
