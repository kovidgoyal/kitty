/*
 * launcher.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <libgen.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#include <sys/syslimits.h>
#include <sys/stat.h>
#include <os/log.h>
#else
#include <limits.h>
#endif
#include "launcher.h"
#include "utils.h"
#define FOR_LAUNCHER
#include "cli-parser-data_generated.h"

#ifndef KITTY_LIB_PATH
#define KITTY_LIB_PATH "../.."
#endif
#ifndef KITTY_LIB_DIR_NAME
#define KITTY_LIB_DIR_NAME "lib"
#endif

static void cleanup_free(void *p) { free(*(void**) p); }
#define RAII_ALLOC(type, name, initializer) __attribute__((cleanup(cleanup_free))) type *name = initializer

static bool being_tested = false;

#ifndef __FreeBSD__
static bool
safe_realpath(const char* src, char *buf, size_t buf_sz) {
    RAII_ALLOC(char, ans, realpath(src, NULL));
    if (ans == NULL) return false;
    safe_snprintf(buf, buf_sz, "%s", ans);
    return true;
}
#endif

typedef struct {
    const char *exe, *exe_dir, *lc_ctype, *lib_dir, *config_dir;
    CLISpec *cli_spec;
    bool launched_by_launch_services, is_quick_access_terminal;
} RunData;

static bool
set_kitty_run_data(RunData *run_data, bool from_source, wchar_t *extensions_dir) {
    PyObject *ans = PyDict_New();
    if (!ans) { PyErr_Print(); return false; }
    PyObject *exe_dir = PyUnicode_DecodeFSDefaultAndSize(run_data->exe_dir, strlen(run_data->exe_dir));
    if (exe_dir == NULL) { fprintf(stderr, "Fatal error: cannot decode exe_dir: %s\n", run_data->exe_dir); PyErr_Print(); Py_CLEAR(ans); return false; }
#define S(key, val) { if (!val) { PyErr_Print(); Py_CLEAR(ans); return false; } int ret = PyDict_SetItemString(ans, #key, val); Py_CLEAR(val); if (ret != 0) { PyErr_Print(); Py_CLEAR(ans); return false; } }
    S(bundle_exe_dir, exe_dir);
    if (from_source) {
        PyObject *one = Py_True; Py_INCREF(one);
        S(from_source, one);
    }
    if (run_data->lc_ctype) {
        PyObject *ctype = PyUnicode_DecodeLocaleAndSize(run_data->lc_ctype, strlen(run_data->lc_ctype), NULL);
        S(lc_ctype_before_python, ctype);
    }
    if (extensions_dir) {
        PyObject *ed = PyUnicode_FromWideChar(extensions_dir, -1);
        S(extensions_dir, ed);
    }
    PyObject *lbls = run_data->launched_by_launch_services ? Py_True : Py_False;
    Py_INCREF(lbls);
    S(launched_by_launch_services, lbls);
    lbls = run_data->is_quick_access_terminal ? Py_True : Py_False;
    Py_INCREF(lbls);
    S(is_quick_access_terminal_app, lbls);

    char buf[PATH_MAX + 1];
    if (run_data->config_dir == NULL) {
        if (get_config_dir(buf, sizeof(buf))) run_data->config_dir = buf;
    }
    if (run_data->config_dir) {
        PyObject *cdir = PyUnicode_DecodeFSDefaultAndSize(run_data->config_dir, strlen(run_data->config_dir));
        if (!cdir) { PyErr_Print(); return false; }
        S(config_dir, cdir);
    }
    PyObject *cli_flags = cli_parse_result_as_python(run_data->cli_spec);
    if (!cli_flags) {
        if (PyErr_Occurred()) PyErr_Print();
        return false;
    }
    S(cli_flags, cli_flags);

#undef S
    int ret = PySys_SetObject("kitty_run_data", ans);
    Py_CLEAR(ans);
    if (ret != 0) { PyErr_Print(); return false; }
    return true;
}


#ifdef FOR_BUNDLE
#include <bypy-freeze.h>

static void
canonicalize_path_wide(const char *srcpath, wchar_t *dest, size_t sz) {
    char buf[sz + 1];
    lexical_absolute_path(srcpath, buf, sz);
    buf[sz] = 0;
    mbstowcs(dest, buf, sz - 1);
    dest[sz-1] = 0;
}

static int
run_embedded(RunData *run_data) {
    bypy_pre_initialize_interpreter(false);
    char extensions_dir_full[PATH_MAX+1] = {0}, python_home_full[PATH_MAX+1] = {0};
#ifdef __APPLE__
    const char *python_relpath = "../Resources/Python/lib";
#else
    const char *python_relpath = "../" KITTY_LIB_DIR_NAME;
#endif
    safe_snprintf(extensions_dir_full, PATH_MAX, "%s/%s/kitty-extensions", run_data->exe_dir, python_relpath);
    wchar_t extensions_dir[PATH_MAX];
    canonicalize_path_wide(extensions_dir_full, extensions_dir, PATH_MAX);
    safe_snprintf(python_home_full, PATH_MAX, "%s/%s/python%s", run_data->exe_dir, python_relpath, PYVER);
    wchar_t python_home[PATH_MAX];
    canonicalize_path_wide(python_home_full, python_home, PATH_MAX);
    bypy_initialize_interpreter(
            L"kitty", python_home, L"kitty_main", extensions_dir, run_data->cli_spec->original_argc, run_data->cli_spec->original_argv);
    if (!set_kitty_run_data(run_data, false, extensions_dir)) return 1;
    set_sys_bool("frozen", true);
    return bypy_run_interpreter();
}

#else

static int
run_embedded(RunData *run_data) {
    bool from_source = false;
#ifdef FROM_SOURCE
    from_source = true;
#endif
    PyStatus status;
    PyPreConfig preconfig;
    PyPreConfig_InitPythonConfig(&preconfig);
    preconfig.utf8_mode = 1;
    preconfig.coerce_c_locale = 1;
#ifdef SET_PYTHON_HOME
    preconfig.isolated = 1;
#endif
    status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) goto fail;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.parse_argv = 0;
    config.optimization_level = 2;
    status = PyConfig_SetBytesArgv(&config, run_data->cli_spec->original_argc, run_data->cli_spec->original_argv);
    if (PyStatus_Exception(status)) goto fail;
    status = PyConfig_SetBytesString(&config, &config.executable, run_data->exe);
    if (PyStatus_Exception(status)) goto fail;
    status = PyConfig_SetBytesString(&config, &config.run_filename, run_data->lib_dir);
    if (PyStatus_Exception(status)) goto fail;
#ifdef SET_PYTHON_HOME
#ifndef __APPLE__
    char pyhome[256];
    safe_snprintf(pyhome, sizeof(pyhome), "%s/%s", run_data->lib_dir, SET_PYTHON_HOME);
    status = PyConfig_SetBytesString(&config, &config.home, pyhome);
    if (PyStatus_Exception(status)) goto fail;
#endif
    config.isolated = 1;
#endif
    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status))  goto fail;
    PyConfig_Clear(&config);
    if (!set_kitty_run_data(run_data, from_source, NULL)) return 1;
    PySys_SetObject("frozen", Py_False);
    return Py_RunMain();
fail:
    PyConfig_Clear(&config);
    if (PyStatus_IsExit(status)) return status.exitcode;
    single_instance_main(-1, NULL, NULL);
    Py_ExitStatusException(status);
}

#endif

// read_exe_path() {{{
#ifdef __APPLE__
static bool
read_exe_path(char *exe, size_t buf_sz) {
    (void)buf_sz;
    uint32_t size = PATH_MAX;
    char apple[PATH_MAX+1] = {0};
    if (_NSGetExecutablePath(apple, &size) != 0) { fprintf(stderr, "Failed to get path to executable\n"); return false; }
    if (!safe_realpath(apple, exe, buf_sz)) { fprintf(stderr, "realpath() failed on the executable's path\n"); return false; }
    return true;
}
#elif defined(__FreeBSD__)
#include <sys/param.h>
#include <sys/sysctl.h>

static bool
read_exe_path(char *exe, size_t buf_sz) {
    int name[] = { CTL_KERN, KERN_PROC, KERN_PROC_PATHNAME, -1 };
    size_t length = buf_sz;
    int error = sysctl(name, 4, exe, &length, NULL, 0);
    if (error < 0 || length <= 1) {
        fprintf(stderr, "failed to get path to executable, sysctl() failed\n");
        return false;
    }
    return true;
}
#elif defined(__NetBSD__)

static bool
read_exe_path(char *exe, size_t buf_sz) {
    if (!safe_realpath("/proc/curproc/exe", exe, buf_sz)) { fprintf(stderr, "Failed to read /proc/curproc/exe\n"); return false; }
    return true;
}

#elif defined(__OpenBSD__)
static bool
read_exe_path(char *exe, size_t buf_sz) {
    const char *path = getenv("PATH");
    if (!path) { fprintf(stderr, "No PATH environment variable set, aborting\n"); return false; }
    char buf[PATH_MAX + 1] = {0};
    strncpy(buf, path, PATH_MAX);
    char *token = strtok(buf, ":");
    while (token != NULL) {
        char q[PATH_MAX + 1] = {0};
        safe_snprintf(q, PATH_MAX, "%s/kitty", token);
        if (safe_realpath(q, exe, buf_sz)) return true;
        token = strtok(NULL, ":");
    }
    fprintf(stderr, "kitty not found in PATH aborting\n");
    return false;
}

#else

static bool
read_exe_path(char *exe, size_t buf_sz) {
    if (!safe_realpath("/proc/self/exe", exe, buf_sz)) { fprintf(stderr, "Failed to read /proc/self/exe\n"); return false; }
    return true;
}
#endif // }}}

static bool
is_valid_fd(int fd)
{
    // This is copied from the python source code as we need the exact same semantics
    // to prevent python from giving us None for sys.stdout and friends.
#if defined(F_GETFD) && ( \
        defined(__linux__) || \
        defined(__APPLE__) || \
        defined(__wasm__))
    return fcntl(fd, F_GETFD) >= 0;
#elif defined(__linux__)
    int fd2 = dup(fd);
    if (fd2 >= 0) {
        close(fd2);
    }
    return (fd2 >= 0);
#else
    struct stat st;
    return (fstat(fd, &st) == 0);
#endif
}

static bool
reopen_to_null(const char *mode, FILE *stream) {
    errno = 0;
    while (true) {
        if (freopen("/dev/null", mode, stream) != NULL) return true;
        if (errno == EINTR) continue;
        perror("Failed to re-open STDIO handle to /dev/null");
        return false;
    }
}

static bool
ensure_working_stdio(void) {
#define C(which, mode) { \
    int fd = fileno(which); \
    if (fd < 0) { if (!reopen_to_null(mode, which)) return false; } \
    else if (!is_valid_fd(fd)) { \
        close(fd); if (!reopen_to_null(mode, which)) return false; \
    }}
    C(stdin, "r") C(stdout, "w") C(stderr, "w")
    return true;
#undef C
}

static bool
is_wrapped_kitten(const char *arg) {
    char buf[64];
    safe_snprintf(buf, sizeof(buf)-1, " %s ", arg);
    return strstr(" " WRAPPED_KITTENS " ", buf);
}

static void
exec_kitten(int argc, char *argv[], char *exe_dir) {
    char exe[PATH_MAX+1] = {0};
    safe_snprintf(exe, PATH_MAX, "%s/kitten", exe_dir);
    argv[0] = "kitten";
    if (being_tested) {
        printf("kitten_exe: %s\n", exe);
        output_argv("argv", argc, argv);
        exit(0);
    }
    errno = 0;
    execv(exe, argv);
    fprintf(stderr, "Failed to execute kitten (%s) with error: %s\n", exe, strerror(errno));
    exit(1);
}

static bool
parse_and_check_kitty_cli(CLISpec *cli_spec, int argc, char **argv) {
    parse_cli_for_kitty(cli_spec, argc, argv);
    if (cli_spec->errmsg) {
        fprintf(stderr, "%s\n", cli_spec->errmsg);
#ifdef __APPLE__
        os_log_error(OS_LOG_DEFAULT, "%{public}s", cli_spec->errmsg);
#endif
        return false;
    }
    return true;
}

static bool
parse_and_check_panel_kitten_cli(CLISpec *cli_spec, int argc, char **argv) {
    parse_cli_for_panel_kitten(cli_spec, argc, argv);
    if (cli_spec->errmsg) {
        fprintf(stderr, "%s\n", cli_spec->errmsg);
#ifdef __APPLE__
        os_log_error(OS_LOG_DEFAULT, "%{public}s", cli_spec->errmsg);
#endif
        return false;
    }
    return true;
}

static int
offset_for_plus_subcommand(int argc, char **argv, const char *name) {
    int offset = 0;
#define arg_eq(num, what) (strcmp(argv[num], what) == 0)
    if (argc > 1 && argv[1][0] == '+' && strcmp(argv[1] + 1, name) == 0) {
        offset = 1;
    } else if (argc > 2 && arg_eq(1, "+") && arg_eq(2, name)) {
        offset = 2;
    }
#undef arg_eq
    return offset;
}

static void
handle_fast_commandline(CLISpec *cli_spec, const char *instance_group_prefix) {
    CLIOptions opts = {0};
    RAII_CLISpec(subcommand_cli_spec);
#define swap_cli_spec \
            subcommand_cli_spec.original_argc = cli_spec->original_argc; \
            subcommand_cli_spec.original_argv = cli_spec->original_argv; \
            cli_spec = &subcommand_cli_spec;
    if (instance_group_prefix == NULL) {
        // Look for +open
        int offset = offset_for_plus_subcommand(cli_spec->original_argc, cli_spec->original_argv, "open");
        if (offset) {
            if (!parse_and_check_kitty_cli(&subcommand_cli_spec, cli_spec->original_argc - offset, cli_spec->original_argv + offset)) exit(1);
            swap_cli_spec;
            opts.open_url_count = cli_spec->argc;
            opts.open_urls = cli_spec->argv;
        }
    } else {
        parse_and_check_panel_kitten_cli(
            &subcommand_cli_spec, cli_spec->original_argc, cli_spec->original_argv);
        swap_cli_spec;
    }
    if (get_bool_cli_val(cli_spec, "help")) return;
    if (get_bool_cli_val(cli_spec, "version")) {
        if (isatty(STDOUT_FILENO)) {
            printf("\x1b[3mkitty\x1b[23m \x1b[32m%s\x1b[39m created by \x1b[1;34mKovid Goyal\x1b[22;39m\n", KITTY_VERSION);
        } else {
            printf("kitty %s created by Kovid Goyal\n", KITTY_VERSION);
        }
        exit(0);
    }
    opts.session = get_string_cli_val(cli_spec, "session");
    if (get_bool_cli_val(cli_spec, "detach")) {
        const char *detached_log = get_string_cli_val(cli_spec, "detached_log");
        if (being_tested) {
            printf("detach: true\n");
            printf("detached_log: %s\n", detached_log ? detached_log : "");
            printf("session: %s\n", opts.session ? opts.session : "");
            exit(0);
        } else {
            int fds[2] = {0};
            if (pipe(fds) == -1) {
                perror("failed to create a pipe"); exit(1);
            }

#define reopen_or_fail(path, mode, which) { errno = 0; if (freopen(path, mode, which) == NULL) { int s = errno; fprintf(stderr, "Failed to redirect %s to %s with error: ", #which, path); errno = s; perror(NULL); exit(1); } }
            if (!(opts.session && ((opts.session[0] == '-' && opts.session[1] == 0) || strcmp(opts.session, "/dev/stdin") == 0)))
                reopen_or_fail("/dev/null", "rb", stdin);
            if (!detached_log || !detached_log[0]) detached_log = "/dev/null";
            reopen_or_fail(detached_log, "ab", stdout);
            reopen_or_fail(detached_log, "ab", stderr);
#undef reopen_or_fail
            if (fork() != 0) {
                // wait until child has done setsid() before exiting so that it doesnt get a SIGHUP,
                // see: https://github.com/kovidgoyal/kitty/issues/8680
                char buf[4];
                errno = 0; while (close(fds[1]) != 0 && errno == EINTR);
                errno = 0; while(read(fds[0], buf, sizeof(buf)) == -1 && errno == EINTR);
                exit(0);
            }
            errno = 0; while (close(fds[0]) != 0 && errno == EINTR);
            setsid();
            errno = 0; while (close(fds[1]) != 0 && errno == EINTR);
        }
    }
    unsetenv("KITTY_SI_DATA");
    if (get_bool_cli_val(cli_spec, "single_instance")) {
        char igbuf[256];
        opts.wait_for_single_instance_window_close = get_bool_cli_val(cli_spec, "wait_for_single_instance_window_close");
        opts.instance_group = get_string_cli_val(cli_spec, "instance_group");
        if (instance_group_prefix && instance_group_prefix[0]) {
            opts.instance_group = get_string_cli_val(cli_spec, "instance_group");
            if (opts.instance_group && opts.instance_group[0]) {
                safe_snprintf(igbuf, sizeof(igbuf), "%s-%s", instance_group_prefix, opts.instance_group ? opts.instance_group : "");
                opts.instance_group = igbuf;
            } else {
                opts.instance_group = instance_group_prefix;
            }
        }
        if (being_tested) {
            output_argv("argv", cli_spec->original_argc, cli_spec->original_argv);
            output_argv("open_urls", opts.open_url_count, opts.open_urls);
            output_values_for_testing(cli_spec);
            printf("single_instance: 1\n");
            printf("instance_group: %s\n", opts.instance_group ? opts.instance_group : "");
            printf("session: %s\n", opts.session ? opts.session : "");
            exit(0);
        } else {
            single_instance_main(cli_spec->original_argc, cli_spec->original_argv, &opts);
        }
    }
}

static bool
delegate_to_kitten_if_possible(int argc, char **argv, char* exe_dir) {
    if (argc > 1 && argv[1][0] == '@') exec_kitten(argc, argv, exe_dir);
    int offset = offset_for_plus_subcommand(argc, argv, "kitten");
    if (offset && argc > offset+1) {
        const char *kitten = argv[offset + 1];
        if (is_wrapped_kitten(kitten)) exec_kitten(argc - offset, argv + offset, exe_dir);
        if (strcmp(kitten, "panel") == 0) {
            offset++;
            CLISpec t = {.original_argv = argv + offset, .original_argc=argc - offset};
            handle_fast_commandline(&t, "panel");
            return true;
        }
    }
    return false;
}

static bool
endswith(const char *str, const char *suffix) {
    size_t strLen = strlen(str);
    size_t suffixLen = strlen(suffix);
    if (suffixLen > strLen) return false;
    return strcmp(str + strLen - suffixLen, suffix) == 0;
}

static void
output_test_data(RunData *rd) {
    printf("launched_by_launch_services: %d\n", rd->launched_by_launch_services);
    printf("is_quick_access_terminal: %d\n", rd->is_quick_access_terminal);
    char buf[PATH_MAX + 1];
    if (rd->config_dir == NULL) {
        if (get_config_dir(buf, sizeof(buf))) rd->config_dir = buf;
    }
    printf("config_dir: %s\n", rd->config_dir ? rd->config_dir : "");
    output_for_testing(rd->cli_spec);
}

int
main(int argc_, char *argv_[], char* envp[]) {
    if (argc_ < 1 || !argv_) { fprintf(stderr, "Invalid argc/argv\n"); return 1; }
    if (argc_ > 1 && strcmp(argv_[1], "+testing-launcher-code") == 0) {
        being_tested = true;
        memmove(argv_ + 1, argv_ + 2, (--argc_ - 1) * sizeof(argv_[0]));
    }
    if (!ensure_working_stdio()) return 1;
    char exe[PATH_MAX+1] = {0};
    if (!read_exe_path(exe, sizeof(exe))) return 1;
    char exe_dir_buf[PATH_MAX+1] = {0};
    strncpy(exe_dir_buf, exe, sizeof(exe_dir_buf));
    char *exe_dir = dirname(exe_dir_buf);

    RAII_ALLOC(const char, lc_ctype, NULL);
    bool launched_by_launch_services = false;
    const char *config_dir = NULL;
    bool is_quick_access_terminal = false;
    argv_array argva = {.argv = argv_, .count = argc_};
#ifdef __APPLE__
    lc_ctype = getenv("LC_CTYPE");
    if (lc_ctype) lc_ctype = strdup(lc_ctype);
    char abuf[PATH_MAX+1];
    is_quick_access_terminal = endswith(exe, "/kitty-quick-access");
    if (getenv("KITTY_LAUNCHED_BY_LAUNCH_SERVICES")) {
        launched_by_launch_services = true;
        unsetenv("KITTY_LAUNCHED_BY_LAUNCH_SERVICES");
        if (!get_config_dir(abuf, sizeof(abuf))) abuf[0] = 0;
        config_dir = abuf;
        if (launched_by_launch_services && config_dir[0]) {
            char cbuf[PATH_MAX];
            safe_snprintf(cbuf, sizeof(cbuf), "%s/macos-launch-services-cmdline", config_dir);
            if (!get_argv_from(cbuf, argva.argv[0], &argva)) exit(1);
        }
    }
#else
    (void)endswith;
#endif
    (void)read_full_file;
    RAII_CLISpec(cli_spec);
    bool handle_fast_commandline_called = delegate_to_kitten_if_possible(argva.count, argva.argv, exe_dir);
    bool ok = parse_and_check_kitty_cli(&cli_spec, argva.count, argva.argv);
    if (!ok) return 1;
    if (!handle_fast_commandline_called) handle_fast_commandline(&cli_spec, NULL);
    int ret=0;
    char lib[PATH_MAX+1] = {0};
    if (KITTY_LIB_PATH[0] == '/') {
        safe_snprintf(lib, PATH_MAX, "%s", KITTY_LIB_PATH);
    } else {
        safe_snprintf(lib, PATH_MAX, "%s/%s", exe_dir, KITTY_LIB_PATH);
    }
    RunData run_data = {
        .exe = exe, .exe_dir = exe_dir, .lib_dir = lib, .cli_spec = &cli_spec, .lc_ctype = lc_ctype,
        .launched_by_launch_services=launched_by_launch_services, .config_dir = config_dir, .is_quick_access_terminal=is_quick_access_terminal,
    };
    if (being_tested) output_test_data(&run_data);
    else ret = run_embedded(&run_data);
    free_argv_array(&argva);
    single_instance_main(-1, NULL, NULL);
    if (!being_tested) Py_FinalizeEx();
    return ret;
}
