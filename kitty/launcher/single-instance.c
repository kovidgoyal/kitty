/*
 * single-instance.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// We rely on data-types.h including Python.h which defines _DARWIN_C_SOURCE
// which we need for _CS_DARWIN_USER_CACHE_DIR
#include "../data-types.h"

#include "launcher.h"
#include "../safe-wrappers.h"
#include <stdbool.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <pwd.h>
#include <sys/types.h>

#define CHARSETS_STORAGE static inline
#define NO_SINGLE_BYTE_CHARSETS
#include "../charsets.c"

#define fail_on_errno(msg) { perror(msg); do_exit(1); }

void
log_error(const char *fmt, ...) {
    va_list ar;
    va_start(ar, fmt);
    vfprintf(stderr, fmt, ar);
    va_end(ar);
}

typedef struct cleanup_data {
    int fd1, fd2;
    bool close_fd1, close_fd2;
    char path1[sizeof(struct sockaddr_un) + 16], path2[sizeof(struct sockaddr_un) + 16];
} cleanup_data;

struct {
    cleanup_data si, notify;
} cleanup_entries = {0};

static void
do_cleanup(cleanup_data *d) {
    if (d->path1[0]) unlink(d->path1);
    if (d->path2[0]) unlink(d->path2);
    if (d->close_fd1) safe_close(d->fd1, __FILE__, __LINE__);
    if (d->close_fd2) safe_close(d->fd2, __FILE__, __LINE__);
}

static void
cleanup(void) {
    do_cleanup(&cleanup_entries.notify);
    do_cleanup(&cleanup_entries.si);
}

static void
do_exit(int code) {
    cleanup();
    exit(code);
}


#ifndef __APPLE__
static bool
is_ok_tmpdir(const char *x) {
    if (!x || !x[0]) return false;
    char path[2048];
    snprintf(path, sizeof(path), "%s/kitty-si-test-tmpdir-XXXXXXXXXXXX", x);
    int fd = safe_mkstemp(path);
    if (fd > -1) {
        safe_close(fd, __FILE__, __LINE__);
        unlink(path);
        return true;
    }
    return false;
}
#endif

static void
get_socket_dir(char *output, size_t output_capacity) {
#define ret_if_ok(x) if (is_ok_tmpdir(x)) { if (snprintf(output, output_capacity, "%s", x) < output_capacity-1); return; }
#ifdef __APPLE__
    if (confstr(_CS_DARWIN_USER_CACHE_DIR, output, output_capacity)) return;
    snprintf(output, output_capacity, "%s", "/Library/Caches");
#else
#define test_env(x) { const char *e = getenv(#x); ret_if_ok(e); }
    test_env(XDG_RUNTIME_DIR); test_env(TMPDIR); test_env(TEMP); test_env(TMP);

    ret_if_ok("/tmp"); ret_if_ok("/var/tmp"); ret_if_ok("/usr/tmp");

    test_env(HOME);

    const char *home = getpwuid(geteuid())->pw_dir;
    ret_if_ok(home);

    if (getcwd(output, output_capacity)) return;
    snprintf(output, output_capacity, "%s", ".");
#undef test_env
#endif
}

static void
set_single_instance_socket(int fd) {
    if (listen(fd, 5) != 0) fail_on_errno("Failed to listen on single instance socket");
    char buf[256];
    snprintf(buf, sizeof(buf), "%d", fd);
    setenv("KITTY_SI_DATA", buf, 1);
}

typedef struct membuf {
    char *data;
    size_t used, capacity;
} membuf;

static void
write_to_membuf(membuf *m, void *data, size_t sz) {
    ensure_space_for(m, data, char, m->used + sz, capacity, 8192, false);
    memcpy(m->data + m->used, data, sz); m->used += sz;
}

static void
write_escaped_char(membuf *m, char ch) {
    char buf[8];
    int n = snprintf(buf, sizeof(buf), "\\u%04x", ch);
    write_to_membuf(m, buf, n);
}

static void
write_json_string(membuf *m, const char *src, size_t src_len) {
    ensure_space_for(m, data, char, m->used + 2 + 8 * src_len, capacity, 8192, false);
    m->data[m->used++] = '"';
    uint32_t codep = 0;
    UTF8State state = 0, prev = UTF8_ACCEPT;
    for (size_t i = 0; i < src_len; i++) {
        switch(decode_utf8(&state, &codep, src[i])) {
            case UTF8_ACCEPT:
                switch(codep) {
                    case '"': write_to_membuf(m, "\\\"", 2); break;
                    case '\\': write_to_membuf(m, "\\\\", 2); break;
                    case '\t': write_to_membuf(m, "\\t", 2); break;
                    case '\n': write_to_membuf(m, "\\n", 2); break;
                    case '\r': write_to_membuf(m, "\\r", 2); break;
START_ALLOW_CASE_RANGE
                    case 0 ... 8: case 11: case 12: case 14 ... 31:
                        write_escaped_char(m, codep); break;
END_ALLOW_CASE_RANGE
                    default: m->used += encode_utf8(codep, m->data + m->used);
                }
                break;
            case UTF8_REJECT:
                state = UTF8_ACCEPT;
                if (prev != UTF8_ACCEPT && i > 0) i--;
                break;
        }
        prev = state;
    }
    m->data[m->used++] = '"';
}

static void
write_json_string_array(membuf *m, int argc, char *argv[]) {
    write_to_membuf(m, "[", 1);
    for (int i = 0; i < argc; i++) {
        if (i) write_to_membuf(m, ",", 1);
        write_json_string(m, argv[i], strlen(argv[i]));
    }
    write_to_membuf(m, "]", 1);
}

static void
read_till_eof(FILE *f, membuf *m) {
    while (!feof(f)) {
        ensure_space_for(m, data, char, m->used + 8192, capacity, 4*8192, false);
        m->used += fread(m->data, 1, m->capacity - m->used, f);
        if (ferror(f)) { fclose(f); fail_on_errno("Failed to read from session file"); }
    }
    // ensure NULL termination
    write_to_membuf(m, "\0", 1); m->used--;
    fclose(f);
}


static bool
bind_unix_socket(int s, const char *basename, struct sockaddr_un *addr, cleanup_data *cleanup) {
    addr->sun_family = AF_UNIX;
    const size_t blen = strlen(basename);
    // First try abstract socket
    addr->sun_path[0] = 0;
    memcpy(addr->sun_path + 1, basename, blen + 1);
    if (safe_bind(s, (struct sockaddr*)addr, sizeof(sa_family_t) + 1 + blen) > -1) return true;
    if (errno != ENOENT) return false;
    // Try an actual filesystem file
    get_socket_dir(addr->sun_path, sizeof(addr->sun_path) - blen - 2);
    size_t dlen = strlen(addr->sun_path);
    while (dlen && addr->sun_path[dlen-1] == '/') dlen--;
    if (snprintf(addr->sun_path + dlen, sizeof(addr->sun_path) - dlen, "/%s", basename) < blen + 1) {
        fprintf(stderr, "Socket directory has path too long for single instance socket file %s\n", addr->sun_path);
        do_exit(1);
    }
    // First lock the socket file using a separate lock file
    char lock_file_path[sizeof(addr->sun_path) + 16];
    snprintf(lock_file_path, sizeof(lock_file_path), "%s.lock", addr->sun_path);
    int fd = safe_open(lock_file_path, O_CREAT | O_WRONLY | O_TRUNC | O_CLOEXEC, S_IRUSR | S_IWUSR);
    if (fd == -1) return false;
    cleanup->close_fd2 = true; cleanup->fd2 = fd;
    snprintf(cleanup->path2, sizeof(cleanup->path2), "%s", lock_file_path);
    if (safe_lockf(fd, F_TLOCK, 0) != 0) {
        int saved_errno = errno;
        safe_close(fd, __FILE__, __LINE__);
        errno = saved_errno;
        if (errno == EAGAIN || errno == EACCES) errno = EADDRINUSE;  // client
        return false;
    }
    // First unlink the socket file and then try to bind it.
    if (unlink(addr->sun_path) != 0 && errno != ENOENT) return false;
    if (safe_bind(s, (struct sockaddr*)addr, sizeof(*addr)) > -1) {
        snprintf(cleanup->path1, sizeof(cleanup->path1), "%s", addr->sun_path);
        return true;
    }
    return false;
}

static int
create_unix_socket(void) {
    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    if (s < 0) fail_on_errno("Failed to create single instance socket object");
    int flags;
    if ((flags = fcntl(s, F_GETFD)) == -1) fail_on_errno("Failed to get fcntl flags for single instance socket");
    if (fcntl(s, F_SETFD, flags | FD_CLOEXEC) == -1) fail_on_errno("Failed to set single instance socket to CLOEXEC");
    return s;
}

extern char **environ;

static void
talk_to_instance(int s, struct sockaddr_un *server_addr, int argc, char *argv[], const CLIOptions *opts) {
    cleanup_entries.si.path2[0] = 0; cleanup_entries.si.path1[0] = 0;
    membuf session_data = {0};
    if (opts->session && opts->session[0]) {
        if (strcmp(opts->session, "none") == 0) {
            session_data.data = "none"; session_data.used = 4;
        } else if (strcmp(opts->session, "-") == 0) {
            read_till_eof(stdin, &session_data);
        } else {
            FILE *f = safe_fopen(opts->session, "r");
            if (f == NULL) fail_on_errno("Failed to open session file for reading");
            read_till_eof(f, &session_data);
        }
    }
    membuf output = {0};
#define w(literal) write_to_membuf(&output, literal, sizeof(literal)-1)
    w("{\"cmd\":\"new_instance\",\"session_data\":");
    if (session_data.used) write_json_string(&output, session_data.data, session_data.used);
    else write_json_string(&output, "", 0);
    w(",\"args\":"); write_json_string_array(&output, argc, argv);
    char cwd[4096];
    if (!getcwd(cwd, sizeof(cwd))) fail_on_errno("Failed to get cwd");
    w(",\"cwd\":"); write_json_string(&output, cwd, strlen(cwd));
    w(",\"environ\":{");
    char **e = environ;
    for (; *e; e++) {
        const char *eq = strchr(*e, '=');
        if (eq) {
            if (e != environ) write_to_membuf(&output, ",", 1);
            write_json_string(&output, *e, eq - *e);
            w(":");
            write_json_string(&output, eq + 1, strlen(eq + 1));
        }
    }
    w("}");

    w(",\"cmdline_args_for_open\":");
    if (opts->open_url_count) write_json_string_array(&output, opts->open_url_count, opts->open_urls);
    else w("[]");

    w(",\"notify_on_os_window_death\":");
    int notify_socket = -1;
    if (opts->wait_for_single_instance_window_close) {
        notify_socket = create_unix_socket();
        cleanup_entries.notify.fd1 = notify_socket; cleanup_entries.notify.close_fd1 = true;
        struct sockaddr_un server_addr;
        char addr[128];
        snprintf(addr, sizeof(addr), "kitty-os-window-close-notify-%d-%d", getpid(), geteuid());
        if (!bind_unix_socket(notify_socket, addr, &server_addr, &cleanup_entries.notify)) fail_on_errno("Failed to bind notification socket");
        size_t len = strlen(server_addr.sun_path);
        if (len == 0) len = 1 + strlen(server_addr.sun_path +1);
        if (listen(notify_socket, 5) != 0) fail_on_errno("Failed to listen on notify socket");
        write_json_string(&output, server_addr.sun_path, len);
    } else w("null");

    w("}");
#undef w
    size_t addr_len = sizeof(sa_family_t);
    if (!server_addr->sun_path[0]) addr_len += 1 + strlen(server_addr->sun_path + 1);
    else addr_len = sizeof(*server_addr);
    if (safe_connect(s, (struct sockaddr*)server_addr, addr_len) != 0) {
        fail_on_errno("Failed to connect to single instance socket");
    }
    size_t pos = 0;
    while (pos < output.used) {
        errno = 0;
        ssize_t nbytes = write(s, output.data + pos, output.used - pos);
        if (nbytes <= 0) {
            if (errno == EAGAIN || errno == EINTR || errno == EWOULDBLOCK) continue;
            break;
        }
        pos += nbytes;
    }
    if (pos < output.used) fail_on_errno("Failed to write message to single instance socket");
    shutdown(s, SHUT_RDWR);
    safe_close(s, __FILE__, __LINE__);
    if (notify_socket > -1) {
        int fd = safe_accept(notify_socket, NULL, NULL);
        if (fd < 0) fail_on_errno("Failed to accept connection on notify socket");
        char rbuf;
        while (true) {
            ssize_t n = recv(notify_socket, &rbuf, 1, 0);
            if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
            break;
        }
        shutdown(notify_socket, SHUT_RDWR);
        safe_close(notify_socket, __FILE__, __LINE__);
    }
}

void
single_instance_main(int argc, char *argv[], const CLIOptions *opts) {
    if (argc == -1) { cleanup(); return; }
    struct sockaddr_un server_addr;
    char addr_buf[sizeof(server_addr.sun_path)-1];
    if (opts->instance_group) snprintf(addr_buf, sizeof(addr_buf), "kitty-ipc-%d-%s", geteuid(), opts->instance_group);
    else snprintf(addr_buf, sizeof(addr_buf), "kitty-ipc-%d", geteuid());

    int s = create_unix_socket();
    cleanup_entries.si.fd1 = s; cleanup_entries.si.close_fd1 = true;
    if (!bind_unix_socket(s, addr_buf, &server_addr, &cleanup_entries.si)) {
        if (errno == EADDRINUSE) { talk_to_instance(s, &server_addr, argc, argv, opts); do_exit(0); }
        else fail_on_errno("Failed to bind single instance socket");
    } else set_single_instance_socket(s);
}
