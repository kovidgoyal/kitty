/*
 * Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// for SA_RESTART
#define _XOPEN_SOURCE 700

// Includes {{{
#include <stdio.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>
#include <termios.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <poll.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#ifdef __APPLE__
#include <util.h>
#include <mach-o/dyld.h>
#include <sys/syslimits.h>
#include <sys/stat.h>
#else
#include <pty.h>
#include <limits.h>
#endif

#define arraysz(x) (sizeof(x)/sizeof(x[0]))

#define MAX(x, y) __extension__ ({ \
    __typeof__ (x) a = (x); __typeof__ (y) b = (y); \
        a > b ? a : b;})
// }}}

static inline int
safe_open(const char *path, int flags, mode_t mode) {
    while (true) {
        int fd = open(path, flags, mode);
        if (fd == -1 && errno == EINTR) continue;
        return fd;
    }
}

static inline void
safe_close(int fd) {
    while(close(fd) != 0 && errno == EINTR);
}

static size_t
strnlength(const char* s, size_t n) {
  const char* found = memchr(s, '\0', n);
  return found ? (size_t)(found-s) : n;
}

bool
set_blocking(int fd, bool blocking) {
   if (fd < 0) return false;
   int flags = fcntl(fd, F_GETFL, 0);
   if (flags == -1) return false;
   flags = blocking ? (flags & ~O_NONBLOCK) : (flags | O_NONBLOCK);
   return (fcntl(fd, F_SETFL, flags) == 0) ? true : false;
}

static int
connect_to_socket_synchronously(const char *addr) {
    struct sockaddr_un sock_addr = {.sun_family=AF_UNIX};
    strncpy(sock_addr.sun_path, addr, sizeof(sock_addr.sun_path) - 1);
    const size_t addrlen = strnlength(sock_addr.sun_path, sizeof(sock_addr.sun_path)) + sizeof(sock_addr.sun_family);
    if (sock_addr.sun_path[0] == '@') sock_addr.sun_path[0] = 0;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (connect(fd, (struct sockaddr*)&sock_addr, addrlen) != 0) {
        if (errno != EINTR && errno != EINPROGRESS) return -1;
        struct pollfd poll_data = {.fd=fd, .events=POLLOUT};
        while (poll (&poll_data, 1, -1) == -1) { if (errno != EINTR) return -1; }
        int socket_error_code = 0;
        socklen_t sizeof_socket_error_code = sizeof(socket_error_code);
        if (getsockopt (fd, SOL_SOCKET, SO_ERROR, &socket_error_code, &sizeof_socket_error_code) == -1) return -1;
        if (socket_error_code != 0) return -1;
    }
    if (fd > -1) set_blocking(fd, false);
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

static int child_master_fd = -1, child_slave_fd = -1;
static char child_tty_name[PATH_MAX] = {0};
static struct winsize self_winsize = {0};
static struct termios self_termios = {0};
static int self_ttyfd = -1, socket_fd = -1, signal_read_fd = -1, signal_write_fd = -1;
static int stdin_pos = -1, stdout_pos = -1, stderr_pos = -1;
static char fd_send_buf[256];
struct iovec launch_msg = {0};
struct msghdr launch_msg_container = {.msg_control = fd_send_buf, .msg_controllen = sizeof(fd_send_buf), .msg_iov = &launch_msg, .msg_iovlen = 1 };
static size_t launch_msg_cap = 0;
char *launch_msg_buf = NULL;

static void
cleanup(void) {
#define cfd(fd) if (fd > -1) { safe_close(fd); fd = -1; }
    cfd(child_master_fd); cfd(child_slave_fd);
    cfd(self_ttyfd); cfd(socket_fd); cfd(signal_read_fd); cfd(signal_write_fd);
#undef cfd
    if (launch_msg_buf) { free(launch_msg_buf); launch_msg.iov_len = 0; launch_msg_buf = NULL; }
}

static bool
get_window_size(void) {
    while (ioctl(self_ttyfd, TIOCGWINSZ, &self_winsize) == -1) {
        if (errno != EINTR) return false;
    }
    return true;
}

static bool
get_termios_state(void) {
    while (tcgetattr(self_ttyfd, &self_termios) != 0) {
        if (errno != EINTR) return false;
    }
    return true;
}

static bool
open_pty(void) {
    while (openpty(&child_master_fd, &child_slave_fd, child_tty_name, &self_termios, &self_winsize) == -1) {
        if (errno != EINTR) return false;
    }
    return true;
}

static void
handle_signal(int sig_num, siginfo_t *si, void *ucontext) {
    (void)sig_num; (void)ucontext;
    int save_err = errno;
    char *buf = (char*)si;
    size_t sz = sizeof(siginfo_t);
    while (signal_write_fd != -1 && sz) {
        // as long as sz is less than PIPE_BUF write will either write all or return -1 with EAGAIN
        // so we are guaranteed atomic writes
        ssize_t ret = write(signal_write_fd, buf, sz);
        if (ret <= 0) {
            if (errno == EINTR) continue;
            break;
        }
        sz -= ret;
        buf += ret;
    }
    errno = save_err;
}

static bool
setup_signal_handler(void) {
    int fds[2];
    if (pipe(fds) != 0) return false;
    signal_read_fd = fds[0]; signal_write_fd = fds[1];
    struct sigaction act = {.sa_sigaction=handle_signal, .sa_flags=SA_SIGINFO | SA_RESTART};
    if (sigaction(SIGWINCH, &act, NULL) != 0) return false;
    return true;
}

static void
setup_stdio_handles(void) {
    int pos = 0;
    if (isatty(STDIN_FILENO)) stdin_pos = pos++;
    if (isatty(STDOUT_FILENO)) stdout_pos = pos++;
    if (isatty(STDERR_FILENO)) stderr_pos = pos++;
}

static bool
ensure_launch_msg_space(size_t sz) {
    if (launch_msg_cap > launch_msg.iov_len + sz) return true;
    const size_t c = MAX(2 * launch_msg_cap, launch_msg_cap + launch_msg.iov_len + sz + 8);
    launch_msg_cap = MAX(c, 64 * 1024);
    launch_msg_buf = realloc(launch_msg_buf, launch_msg_cap);
    return launch_msg_buf != NULL;
}

static bool
write_item_to_launch_msg(const char *prefix, const char *data) {
    size_t prefixlen = strlen(prefix), datalen = strlen(data), msg_len = 8 + prefixlen + datalen;
    if (!ensure_launch_msg_space(msg_len)) return false;
    memcpy(launch_msg_buf + launch_msg.iov_len, prefix, prefixlen);
    launch_msg.iov_len += prefixlen;
    launch_msg_buf[launch_msg.iov_len++] = ':';
    memcpy(launch_msg_buf + launch_msg.iov_len, data, datalen);
    launch_msg.iov_len += datalen;
    launch_msg_buf[launch_msg.iov_len++] = 0;
    launch_msg.iov_base = launch_msg_buf;
    return true;
}

extern char **environ;

static bool
create_launch_msg(int argc, char *argv[]) {
#define w(prefix, data) { if (!write_item_to_launch_msg(prefix, data)) return false; }
    static char buf[4*PATH_MAX];
    w("tty_name", child_tty_name);
    if (getcwd(buf, sizeof(buf))) { w("cwd", buf); }
    for (int i = 0; i < argc; i++) w("argv", argv[i]);
    char **s = environ;
    for (; *s; s++) w("env", *s);
    struct cmsghdr *cmsg = CMSG_FIRSTHDR(&launch_msg_container);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = 0;
#define sio(which, x) if (which##_pos > -1) { snprintf(buf, sizeof(buf), "%d", which##_pos); w(#which, buf); int fd = x; memcpy(CMSG_DATA(cmsg) + cmsg->cmsg_len, &fd, sizeof(fd)); cmsg->cmsg_len += sizeof(fd);  }
    sio(stdin, STDIN_FILENO); sio(stdout, STDOUT_FILENO); sio(stderr, STDERR_FILENO);
#undef sio
    launch_msg_container.msg_controllen = CMSG_SPACE(cmsg->cmsg_len);
    w("finish", "");
    return true;
#undef w
}

static char exitcode_buf[16] = {0};
static int exit_status = EXIT_FAILURE;

static bool
send_launch_msg(void) {
    ssize_t n;
    while ((n = sendmsg(socket_fd, &launch_msg_container, MSG_NOSIGNAL)) < 0 && errno == EINTR);
    if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) return true;
        return false;
    }
    // some bytes sent null out the control msg data as it is already sent
    launch_msg_container.msg_controllen = 0;
    launch_msg_container.msg_control = NULL;
    if ((size_t)n > launch_msg.iov_len) launch_msg.iov_len = 0;
    else launch_msg.iov_len -= n;
    launch_msg.iov_base = (char*)launch_msg.iov_base + n;
    return true;
}

static bool
parse_long(const char *str, long *val) {
    char *temp;
    bool rc = true;
    errno = 0;
    const long t = strtol(str, &temp, 0);
    if (temp == str || *temp != '\0' || ((*val == LONG_MIN || *val == LONG_MAX) && errno == ERANGE)) rc = false;
    *val = t;
    return rc;
}

static bool
parse_int(const char *str, int *val) {
    long lval;
    if (!parse_long(str, &lval)) return false;
    *val = lval;
    return true;
}


static void
loop(int socket_fd) {
#define fail(s) { perror(s); return; }
#define check_fd(which, name) { if (poll_data[which].revents & POLLERR) { fprintf(stderr, "File descriptor %s failed\n", #name); return; } if (poll_data[which].revents & POLLHUP); { fprintf(stderr, "File descriptor %s hungup\n", #name); return; } }
    struct pollfd poll_data[4];
    poll_data[0].fd = self_ttyfd; poll_data[0].events = POLLIN;
    poll_data[1].fd = child_master_fd; poll_data[1].events = POLLIN;
    poll_data[2].fd = socket_fd; poll_data[2].events = POLLIN;
    poll_data[3].fd = signal_read_fd; poll_data[3].events = POLLIN;

    while (true) {
        for (size_t i = 0; i < arraysz(poll_data); i++) poll_data[i].revents = 0;
        poll_data[2].events = POLLIN | (launch_msg.iov_len ? POLLOUT : 0);
        while (poll(poll_data, 1, -1) == -1) { if (errno != EINTR) fail("poll() failed"); }
        check_fd(0, self_ttyfd); check_fd(1, child_master_fd); check_fd(3, signal_read_fd);

        // socket_fd
        if (poll_data[2].revents & POLLERR) {
            fprintf(stderr, "File descriptor %s failed\n", "socket_fd"); return;
        }
        if (poll_data[2].revents & POLLHUP) {
            if (exitcode_buf[0]) { parse_int(exitcode_buf, &exit_status); }
            return;
        }
        if (poll_data[2].revents & POLLOUT) {
            if (!send_launch_msg()) fail("sending launch message failed");
        }
    }
#undef check_fd
#undef fail
}

static void
use_prewarmed_process(int argc, char *argv[]) {
    const char *env_addr = getenv("KITTY_PREWARM_SOCKET");
    if (!env_addr || !*env_addr || !is_prewarmable(argc, argv)) return;
    self_ttyfd = safe_open(ctermid(NULL), O_RDWR, 0);
#define fail(s) { perror(s); cleanup(); return; }
    if (self_ttyfd == -1) fail("Failed to open controlling terminal");
    if (!get_window_size()) fail("Failed to get window size of controlling terminal");
    if (!get_termios_state()) fail("Failed to get termios state of controlling terminal");
    if (!open_pty()) fail("Failed to open slave pty");
    setup_stdio_handles();
    if (!create_launch_msg(argc, argv)) fail("Failed to open controlling terminal");
    if (!setup_signal_handler()) fail("Failed to setup signal handling");
    socket_fd = connect_to_socket_synchronously(env_addr);
    if (socket_fd < 0) fail("Failed to connect to prewarm socket");
#undef fail

    loop(socket_fd);
    cleanup();
    exit(exit_status);
}
