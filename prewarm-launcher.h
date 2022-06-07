/*
 * Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// needed for strnlen
#define _XOPEN_SOURCE 700

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

static int
connect_to_socket_synchronously(const char *addr) {
    struct sockaddr_un sock_addr = {.sun_family=AF_UNIX};
    strncpy(sock_addr.sun_path, addr, sizeof(sock_addr.sun_path) - 1);
    const size_t addrlen = strnlen(sock_addr.sun_path, sizeof(sock_addr.sun_path)) + sizeof(sock_addr.sun_family);
    if (sock_addr.sun_path[0] == '@') sock_addr.sun_path[0] = 0;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (connect(fd, (struct sockaddr*)&sock_addr, addrlen) != 0) {
        if (errno != EINTR) return -1;
        struct pollfd poll_data = {.fd=fd, .events=POLLOUT};
        while (poll (&poll_data, 1, -1) == -1) { if (errno != EINTR) return -1; }
        int socket_error_code = 0;
        socklen_t sizeof_socket_error_code = sizeof(socket_error_code);
        if (getsockopt (fd, SOL_SOCKET, SO_ERROR, &socket_error_code, &sizeof_socket_error_code) == -1) return -1;
        if (socket_error_code != 0) return -1;
    }
    return fd;
}

static bool
is_prewarmable(int argc, char *argv[]) {
    if (argc < 2) return false;
    if (argv[1][0] != '+') return false;
    if (argv[1][1] != 0) return strcmp(argv[1], "+open") != 0;
    if (argc < 3) return false;
    return strcmp(argv[2], "open") != 0;
}

static void
use_prewarmed_process(int argc, char *argv[]) {
    const char *env_addr = getenv("KITTY_PREWARM_SOCKET_ADDRESS");
    if (!env_addr || !*env_addr || !is_prewarmable(argc, argv)) return;
    int fd = connect_to_socket_synchronously(env_addr);
    if (fd < 0) return;
}
