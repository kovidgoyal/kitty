// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ssh

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/kovidgoyal/kitty"
	"io"
	"io/fs"
	"maps"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"os/user"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/themes"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/shell_integration"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/secrets"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
	"github.com/kovidgoyal/kitty/tools/utils/shm"

	"golang.org/x/sys/unix"
)

var _ = fmt.Print

func get_destination(hostname string) (username, hostname_for_match string) {
	u, err := user.Current()
	if err == nil {
		username = u.Username
	}
	hostname_for_match = hostname
	parsed := false
	if strings.HasPrefix(hostname, "ssh://") {
		p, err := url.Parse(hostname)
		if err == nil {
			hostname_for_match = p.Hostname()
			parsed = true
			if p.User.Username() != "" {
				username = p.User.Username()
			}
		}
	} else if strings.Contains(hostname, "@") && hostname[0] != '@' {
		username, hostname_for_match, _ = strings.Cut(hostname, "@")
		parsed = true
	}
	if !parsed && strings.Contains(hostname, "@") && hostname[0] != '@' {
		_, hostname_for_match, _ = strings.Cut(hostname, "@")
	}
	return
}

func read_data_from_shared_memory(shm_name string) ([]byte, error) {
	data, err := shm.ReadWithSizeAndUnlink(shm_name, func(s fs.FileInfo) error {
		if stat, ok := s.Sys().(syscall.Stat_t); ok {
			if os.Getuid() != int(stat.Uid) || os.Getgid() != int(stat.Gid) {
				return fmt.Errorf("Incorrect owner on SHM file")
			}
		}
		if s.Mode().Perm() != 0o600 {
			return fmt.Errorf("Incorrect permissions on SHM file")
		}
		return nil
	})
	return data, err
}

func add_cloned_env(val string) (ans map[string]string, err error) {
	data, err := read_data_from_shared_memory(val)
	if err != nil {
		return nil, err
	}
	err = json.Unmarshal(data, &ans)
	return ans, err
}

func parse_kitten_args(found_extra_args []string, username, hostname_for_match string) (overrides []string, literal_env map[string]string, ferr error) {
	literal_env = make(map[string]string)
	overrides = make([]string, 0, 4)
	for i, a := range found_extra_args {
		if i%2 == 0 {
			continue
		}
		if key, val, found := strings.Cut(a, "="); found {
			if key == "clone_env" {
				le, err := add_cloned_env(val)
				if err != nil {
					if !errors.Is(err, fs.ErrNotExist) {
						return nil, nil, ferr
					}
				} else if le != nil {
					literal_env = le
				}
			} else if key != "hostname" {
				overrides = append(overrides, key+"="+val)
			}
		}
	}
	return
}

func connection_sharing_args(kitty_pid int) ([]string, error) {
	rd := utils.RuntimeDir()
	// Bloody OpenSSH generates a 40 char hash and in creating the socket
	// appends a 27 char temp suffix to it. Socket max path length is approx
	// ~104 chars. And on idiotic Apple the path length to the runtime dir
	// (technically the cache dir since Apple has no runtime dir and thinks it's
	// a great idea to delete files in /tmp) is ~48 chars.
	if len(rd) > 35 {
		idiotic_design := fmt.Sprintf("/tmp/kssh-rdir-%d", os.Geteuid())
		if err := utils.AtomicCreateSymlink(rd, idiotic_design); err != nil {
			return nil, err
		}
		rd = idiotic_design
	}
	cp := strings.Replace(kitty.SSHControlMasterTemplate, "{kitty_pid}", strconv.Itoa(kitty_pid), 1)
	cp = strings.Replace(cp, "{ssh_placeholder}", "%C", 1)
	return []string{
		"-o", "ControlMaster=auto",
		"-o", "ControlPath=" + filepath.Join(rd, cp),
		"-o", "ControlPersist=yes",
		"-o", "ServerAliveInterval=60",
		"-o", "ServerAliveCountMax=5",
		"-o", "TCPKeepAlive=no",
	}, nil
}

func set_askpass() (need_to_request_data bool) {
	need_to_request_data = true
	sentinel := filepath.Join(utils.CacheDir(), "openssh-is-new-enough-for-askpass")
	_, err := os.Stat(sentinel)
	sentinel_exists := err == nil
	if sentinel_exists || GetSSHVersion().SupportsAskpassRequire() {
		if !sentinel_exists {
			_ = os.WriteFile(sentinel, []byte{0}, 0o644)
		}
		need_to_request_data = false
	}
	exe, err := os.Executable()
	if err == nil {
		os.Setenv("SSH_ASKPASS", exe)
		os.Setenv("KITTY_KITTEN_RUN_MODULE", "ssh_askpass")
		if !need_to_request_data {
			os.Setenv("SSH_ASKPASS_REQUIRE", "force")
		}
	} else {
		need_to_request_data = true
	}
	return
}

type connection_data struct {
	remote_args        []string
	host_opts          *Config
	hostname_for_match string
	username           string
	echo_on            bool
	request_data       bool
	literal_env        map[string]string
	listen_on          string
	test_script        string
	dont_create_shm    bool

	shm_name         string
	script_type      string
	rcmd             []string
	replacements     map[string]string
	request_id       string
	bootstrap_script string
}

func get_effective_ksi_env_var(x string) string {
	parts := strings.Split(strings.TrimSpace(strings.ToLower(x)), " ")
	current := utils.NewSetWithItems(parts...)
	if current.Has("disabled") {
		return ""
	}
	allowed := utils.NewSetWithItems(kitty.AllowedShellIntegrationValues...)
	if !current.IsSubsetOf(allowed) {
		return RelevantKittyOpts().Shell_integration
	}
	return x
}

func serialize_env(cd *connection_data, get_local_env func(string) (string, bool)) (string, string) {
	ksi := ""
	if cd.host_opts.Shell_integration == "inherited" {
		ksi = get_effective_ksi_env_var(RelevantKittyOpts().Shell_integration)
	} else {
		ksi = get_effective_ksi_env_var(cd.host_opts.Shell_integration)
	}
	env := make([]*EnvInstruction, 0, 8)
	add_env := func(key, val string, fallback ...string) *EnvInstruction {
		if val == "" && len(fallback) > 0 {
			val = fallback[0]
		}
		if val != "" {
			env = append(env, &EnvInstruction{key: key, val: val, literal_quote: true})
			return env[len(env)-1]
		}
		return nil
	}
	add_non_literal_env := func(key, val string, fallback ...string) *EnvInstruction {
		ans := add_env(key, val, fallback...)
		if ans != nil {
			ans.literal_quote = false
		}
		return ans
	}
	for k, v := range cd.literal_env {
		add_env(k, v)
	}
	add_env("TERM", os.Getenv("TERM"), RelevantKittyOpts().Term)
	add_env("COLORTERM", "truecolor")
	env = append(env, cd.host_opts.Env...)
	add_env("KITTY_WINDOW_ID", os.Getenv("KITTY_WINDOW_ID"))
	add_env("WINDOWID", os.Getenv("WINDOWID"))
	if ksi != "" {
		add_env("KITTY_SHELL_INTEGRATION", ksi)
	} else {
		env = append(env, &EnvInstruction{key: "KITTY_SHELL_INTEGRATION", delete_on_remote: true})
	}
	add_non_literal_env("KITTY_SSH_KITTEN_DATA_DIR", cd.host_opts.Remote_dir)
	add_non_literal_env("KITTY_LOGIN_SHELL", cd.host_opts.Login_shell)
	add_non_literal_env("KITTY_LOGIN_CWD", cd.host_opts.Cwd)
	if cd.host_opts.Remote_kitty != Remote_kitty_no {
		add_env("KITTY_REMOTE", cd.host_opts.Remote_kitty.String())
	}
	add_env("KITTY_PUBLIC_KEY", os.Getenv("KITTY_PUBLIC_KEY"))
	if cd.listen_on != "" {
		add_env("KITTY_LISTEN_ON", cd.listen_on)
	}
	return final_env_instructions(cd.script_type == "py", get_local_env, env...), ksi
}

func make_tarfile(cd *connection_data, get_local_env func(string) (string, bool)) ([]byte, error) {
	env_script, ksi := serialize_env(cd, get_local_env)
	w := bytes.Buffer{}
	w.Grow(64 * 1024)
	gw, err := gzip.NewWriterLevel(&w, gzip.BestCompression)
	if err != nil {
		return nil, err
	}
	tw := tar.NewWriter(gw)
	rd := strings.TrimRight(cd.host_opts.Remote_dir, "/")
	seen := make(map[file_unique_id]string, 32)
	add := func(h *tar.Header, data []byte) (err error) {
		// some distro's like nix mess with installed file permissions so ensure
		// files are at least readable and writable by owning user
		h.Mode |= 0o600
		err = tw.WriteHeader(h)
		if err != nil {
			return
		}
		if data != nil {
			_, err := tw.Write(data)
			if err != nil {
				return err
			}
		}
		return
	}
	for _, ci := range cd.host_opts.Copy {
		err = ci.get_file_data(add, seen)
		if err != nil {
			return nil, err
		}
	}
	type fe struct {
		arcname string
		data    []byte
	}
	now := time.Now()
	add_data := func(items ...fe) error {
		for _, item := range items {
			err := add(
				&tar.Header{
					Typeflag: tar.TypeReg, Name: item.arcname, Format: tar.FormatPAX, Size: int64(len(item.data)),
					Mode: 0o644, ModTime: now, ChangeTime: now, AccessTime: now,
				}, item.data)
			if err != nil {
				return err
			}
		}
		return nil
	}
	add_entries := func(prefix string, items ...shell_integration.Entry) error {
		for _, item := range items {
			err := add(
				&tar.Header{
					Typeflag: item.Metadata.Typeflag, Name: path.Join(prefix, path.Base(item.Metadata.Name)), Format: tar.FormatPAX,
					Size: int64(len(item.Data)), Mode: item.Metadata.Mode, ModTime: item.Metadata.ModTime,
					AccessTime: item.Metadata.AccessTime, ChangeTime: item.Metadata.ChangeTime,
				}, item.Data)
			if err != nil {
				return err
			}
		}
		return nil

	}
	if err = add_data(fe{"data.sh", utils.UnsafeStringToBytes(env_script)}); err != nil {
		return nil, err
	}
	if cd.script_type == "sh" {
		if err = add_data(fe{"bootstrap-utils.sh", shell_integration.Data()[path.Join("shell-integration/ssh/bootstrap-utils.sh")].Data}); err != nil {
			return nil, err
		}
	}
	if ksi != "" {
		for _, fname := range shell_integration.Data().FilesMatching(
			"shell-integration/",
			"shell-integration/ssh/.+",        // bootstrap files are sent as command line args
			"shell-integration/zsh/kitty.zsh", // backward compat file not needed by ssh kitten
		) {
			arcname := path.Join("home/", rd, "/", path.Dir(fname))
			err = add_entries(arcname, shell_integration.Data()[fname])
			if err != nil {
				return nil, err
			}
		}
	}
	if cd.host_opts.Remote_kitty != Remote_kitty_no {
		arcname := path.Join("home/", rd, "/kitty")
		err = add_data(fe{arcname + "/version", utils.UnsafeStringToBytes(kitty.VersionString)})
		if err != nil {
			return nil, err
		}
		for _, x := range []string{"kitty", "kitten"} {
			err = add_entries(path.Join(arcname, "bin"), shell_integration.Data()[path.Join("shell-integration", "ssh", x)])
			if err != nil {
				return nil, err
			}
		}
	}
	err = add_entries(path.Join("home", ".terminfo"), shell_integration.Data()["terminfo/kitty.terminfo"])
	if err == nil {
		err = add_entries(path.Join("home", ".terminfo", "x"), shell_integration.Data()["terminfo/x/"+kitty.DefaultTermName])
	}
	if err == nil {
		err = tw.Close()
		if err == nil {
			err = gw.Close()
		}
	}
	return w.Bytes(), err
}

func prepare_home_command(cd *connection_data) string {
	is_python := cd.script_type == "py"
	homevar := ""
	for _, ei := range cd.host_opts.Env {
		if ei.key == "HOME" && !ei.delete_on_remote {
			if ei.copy_from_local {
				homevar = os.Getenv("HOME")
			} else {
				homevar = ei.val
			}
		}
	}
	export_home_cmd := ""
	if homevar != "" {
		if is_python {
			export_home_cmd = base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(homevar))
		} else {
			export_home_cmd = fmt.Sprintf("export HOME=%s; cd \"$HOME\"", utils.QuoteStringForSH(homevar))
		}
	}
	return export_home_cmd
}

func prepare_exec_cmd(cd *connection_data) string {
	// ssh simply concatenates multiple commands using a space see
	// line 1129 of ssh.c and on the remote side sshd.c runs the
	// concatenated command as shell -c cmd
	if cd.script_type == "py" {
		return base64.RawStdEncoding.EncodeToString(utils.UnsafeStringToBytes(strings.Join(cd.remote_args, " ")))
	}
	args := make([]string, len(cd.remote_args))
	for i, arg := range cd.remote_args {
		args[i] = strings.ReplaceAll(arg, "'", "'\"'\"'")
	}
	return "unset KITTY_SHELL_INTEGRATION; exec \"$login_shell\" -c '" + strings.Join(args, " ") + "'"
}

var data_shm shm.MMap

func prepare_script(script string, replacements map[string]string) string {
	if _, found := replacements["EXEC_CMD"]; !found {
		replacements["EXEC_CMD"] = ""
	}
	if _, found := replacements["EXPORT_HOME_CMD"]; !found {
		replacements["EXPORT_HOME_CMD"] = ""
	}
	keys := utils.Keys(replacements)
	for i, key := range keys {
		keys[i] = "\\b" + key + "\\b"
	}
	pat := regexp.MustCompile(strings.Join(keys, "|"))
	return pat.ReplaceAllStringFunc(script, func(key string) string { return replacements[key] })
}

func bootstrap_script(cd *connection_data) (err error) {
	if cd.request_id == "" {
		cd.request_id = os.Getenv("KITTY_PID") + "-" + os.Getenv("KITTY_WINDOW_ID")
	}
	export_home_cmd := prepare_home_command(cd)
	exec_cmd := ""
	if len(cd.remote_args) > 0 {
		exec_cmd = prepare_exec_cmd(cd)
	}
	pw, err := secrets.TokenHex()
	if err != nil {
		return err
	}
	tfd, err := make_tarfile(cd, os.LookupEnv)
	if err != nil {
		return err
	}
	data := map[string]string{
		"tarfile":  base64.StdEncoding.EncodeToString(tfd),
		"pw":       pw,
		"hostname": cd.hostname_for_match, "username": cd.username,
	}
	encoded_data, err := json.Marshal(data)
	if err == nil && !cd.dont_create_shm {
		data_shm, err = shm.CreateTemp(fmt.Sprintf("kssh-%d-", os.Getpid()), uint64(len(encoded_data)+8))
		if err == nil {
			err = shm.WriteWithSize(data_shm, encoded_data, 0)
			if err == nil {
				err = data_shm.Flush()
			}
		}
	}
	if err != nil {
		return err
	}
	if !cd.dont_create_shm {
		cd.shm_name = data_shm.Name()
	}
	sensitive_data := map[string]string{"REQUEST_ID": cd.request_id, "DATA_PASSWORD": pw, "PASSWORD_FILENAME": cd.shm_name}
	replacements := map[string]string{
		"EXPORT_HOME_CMD": export_home_cmd,
		"EXEC_CMD":        exec_cmd,
		"TEST_SCRIPT":     cd.test_script,
	}
	add_bool := func(ok bool, key string) {
		if ok {
			replacements[key] = "1"
		} else {
			replacements[key] = "0"
		}
	}
	add_bool(cd.request_data, "REQUEST_DATA")
	add_bool(cd.echo_on, "ECHO_ON")
	sd := maps.Clone(replacements)
	if cd.request_data {
		maps.Copy(sd, sensitive_data)
	}
	maps.Copy(replacements, sensitive_data)
	cd.replacements = replacements
	cd.bootstrap_script = utils.UnsafeBytesToString(shell_integration.Data()["shell-integration/ssh/bootstrap."+cd.script_type].Data)
	cd.bootstrap_script = prepare_script(cd.bootstrap_script, sd)
	return err
}

func wrap_bootstrap_script(cd *connection_data) {
	// sshd will execute the command we pass it by join all command line
	// arguments with a space and passing it as a single argument to the users
	// login shell with -c. If the user has a non POSIX login shell it might
	// have different escaping semantics and syntax, so the command it should
	// execute has to be as simple as possible, basically of the form
	// interpreter -c unwrap_script escaped_bootstrap_script
	// The unwrap_script is responsible for unescaping the bootstrap script and
	// executing it.
	encoded_script := ""
	unwrap_script := ""
	if cd.script_type == "py" {
		encoded_script = base64.StdEncoding.EncodeToString(utils.UnsafeStringToBytes(cd.bootstrap_script))
		unwrap_script = `"import base64, sys; eval(compile(base64.standard_b64decode(sys.argv[-1]), 'bootstrap.py', 'exec'))"`
	} else {
		// We can't rely on base64 being available on the remote system, so instead
		// we quote the bootstrap script by replacing ' and \ with \v and \f
		// also replacing \n and ! with \r and \b for tcsh
		// finally surrounding with '
		encoded_script = "'" + strings.NewReplacer("'", "\v", "\\", "\f", "\n", "\r", "!", "\b").Replace(cd.bootstrap_script) + "'"
		unwrap_script = `'eval "$(echo "$0" | tr \\\v\\\f\\\r\\\b \\\047\\\134\\\n\\\041)"' `
	}
	cd.rcmd = []string{"exec", cd.host_opts.Interpreter, "-c", unwrap_script, encoded_script}
}

func get_remote_command(cd *connection_data) error {
	interpreter := cd.host_opts.Interpreter
	q := strings.ToLower(path.Base(interpreter))
	is_python := strings.Contains(q, "python")
	cd.script_type = "sh"
	if is_python {
		cd.script_type = "py"
	}
	err := bootstrap_script(cd)
	if err != nil {
		return err
	}
	wrap_bootstrap_script(cd)
	return nil
}

var debugprintln = tty.DebugPrintln
var _ = debugprintln

func drain_potential_tty_garbage(term *tty.Term) {
	err := term.ApplyOperations(tty.TCSANOW, tty.SetRaw)
	if err != nil {
		return
	}
	canary, err := secrets.TokenHex()
	if err != nil {
		return
	}
	dcs, err := tui.DCSToKitty("echo", canary)
	q := utils.UnsafeStringToBytes(canary)
	if err != nil {
		return
	}
	err = term.WriteAllString(dcs)
	if err != nil {
		return
	}
	data := make([]byte, 0)
	give_up_at := time.Now().Add(2 * time.Second)
	buf := make([]byte, 0, 8192)
	for !bytes.Contains(data, q) {
		buf = buf[:cap(buf)]
		timeout := time.Until(give_up_at)
		if timeout < 0 {
			break
		}
		n, err := term.ReadWithTimeout(buf, timeout)
		if err != nil {
			break
		}
		data = append(data, buf[:n]...)
	}
}

func change_colors(color_scheme string) (ans string, err error) {
	if color_scheme == "" {
		return
	}
	var theme *themes.Theme
	if !strings.HasSuffix(color_scheme, ".conf") {
		cs := os.ExpandEnv(color_scheme)
		tc, closer, err := themes.LoadThemes(-1)
		if err != nil && errors.Is(err, themes.ErrNoCacheFound) {
			tc, closer, err = themes.LoadThemes(time.Hour * 24)
		}
		if err != nil {
			return "", err
		}
		defer closer.Close()
		theme = tc.ThemeByName(cs)
		if theme == nil {
			return "", fmt.Errorf("No theme named %#v found", cs)
		}
	} else {
		theme, err = themes.ThemeFromFile(utils.ResolveConfPath(color_scheme))
		if err != nil {
			return "", err
		}
	}
	ans, err = theme.AsEscapeCodes()
	if err == nil {
		ans = "\033[#P" + ans
	}
	return
}

func run_ssh(ssh_args, server_args, found_extra_args []string) (rc int, err error) {
	go shell_integration.Data()
	go RelevantKittyOpts()
	defer func() {
		if data_shm != nil {
			data_shm.Close()
			_ = data_shm.Unlink()
		}
	}()
	cmd := append([]string{SSHExe()}, ssh_args...)
	cd := connection_data{remote_args: server_args[1:]}
	hostname := server_args[0]
	if len(cd.remote_args) == 0 {
		cmd = append(cmd, "-t")
	}
	insertion_point := len(cmd)
	cmd = append(cmd, "--", hostname)
	uname, hostname_for_match := get_destination(hostname)
	overrides, literal_env, err := parse_kitten_args(found_extra_args, uname, hostname_for_match)
	if err != nil {
		return 1, err
	}
	host_opts, bad_lines, err := load_config(hostname_for_match, uname, overrides)
	if err != nil {
		return 1, err
	}
	if len(bad_lines) > 0 {
		for _, x := range bad_lines {
			fmt.Fprintf(os.Stderr, "Ignoring bad config line: %s:%d with error: %s", filepath.Base(x.Src_file), x.Line_number, x.Err)
		}
	}
	if host_opts.Delegate != "" {
		delegate_cmd, err := shlex.Split(host_opts.Delegate)
		if err != nil {
			return 1, fmt.Errorf("Could not parse delegate command: %#v with error: %w", host_opts.Delegate, err)
		}
		return 1, unix.Exec(utils.FindExe(delegate_cmd[0]), utils.Concat(delegate_cmd, ssh_args, server_args), os.Environ())
	}
	master_is_alive, master_checked := false, false
	var control_master_args []string
	if host_opts.Share_connections {
		kpid, err := strconv.Atoi(os.Getenv("KITTY_PID"))
		if err != nil {
			return 1, fmt.Errorf("Invalid KITTY_PID env var not an integer: %#v", os.Getenv("KITTY_PID"))
		}
		control_master_args, err = connection_sharing_args(kpid)
		if err != nil {
			return 1, err
		}
		cmd = slices.Insert(cmd, insertion_point, control_master_args...)
	}
	use_kitty_askpass := host_opts.Askpass == Askpass_native || (host_opts.Askpass == Askpass_unless_set && os.Getenv("SSH_ASKPASS") == "")
	need_to_request_data := true
	if use_kitty_askpass {
		need_to_request_data = set_askpass()
	}
	master_is_functional := func() bool {
		if master_checked {
			return master_is_alive
		}
		master_checked = true
		check_cmd := slices.Insert(cmd, 1, "-O", "check")
		master_is_alive = exec.Command(check_cmd[0], check_cmd[1:]...).Run() == nil
		return master_is_alive
	}

	if need_to_request_data && host_opts.Share_connections && master_is_functional() {
		need_to_request_data = false
	}
	run_control_master := func() error {
		cmcmd := slices.Clone(cmd[:insertion_point])
		cmcmd = append(cmcmd, control_master_args...)
		cmcmd = append(cmcmd, "-N", "-f")
		cmcmd = append(cmcmd, "--", hostname)
		c := exec.Command(cmcmd[0], cmcmd[1:]...)
		c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
		err := c.Run()
		if err != nil {
			err = fmt.Errorf("Failed to start SSH ControlMaster with cmdline: %s and error: %w", strings.Join(cmcmd, " "), err)
		}
		master_checked = false
		master_is_alive = false
		return err
	}
	if host_opts.Forward_remote_control && os.Getenv("KITTY_LISTEN_ON") != "" {
		if !host_opts.Share_connections {
			return 1, fmt.Errorf("Cannot use forward_remote_control=yes without share_connections=yes as it relies on SSH Controlmasters")
		}
		if !master_is_functional() {
			if err = run_control_master(); err != nil {
				return 1, err
			}
			if !master_is_functional() {
				return 1, fmt.Errorf("SSH ControlMaster not functional after being started explicitly")
			}
		}
		protocol, listen_on, found := strings.Cut(os.Getenv("KITTY_LISTEN_ON"), ":")
		if !found {
			return 1, fmt.Errorf("Invalid KITTY_LISTEN_ON: %#v", os.Getenv("KITTY_LISTEN_ON"))
		}
		if protocol == "unix" && strings.HasPrefix(listen_on, "@") {
			return 1, fmt.Errorf("Cannot forward kitty remote control socket when an abstract UNIX socket (%s) is used, due to limitations in OpenSSH. Use either a path based one or a TCP socket", listen_on)
		}
		cmcmd := slices.Clone(cmd[:insertion_point])
		cmcmd = append(cmcmd, control_master_args...)
		cmcmd = append(cmcmd, "-R", "0:"+listen_on, "-O", "forward")
		cmcmd = append(cmcmd, "--", hostname)
		c := exec.Command(cmcmd[0], cmcmd[1:]...)
		b := bytes.Buffer{}
		c.Stdout = &b
		c.Stderr = os.Stderr
		if err := c.Run(); err != nil {
			return 1, fmt.Errorf("%s\nSetup of port forward in SSH ControlMaster failed with error: %w", b.String(), err)
		}
		port, err := strconv.Atoi(strings.TrimSpace(b.String()))
		if err != nil {
			os.Stderr.Write(b.Bytes())
			return 1, fmt.Errorf("Setup of port forward in SSH ControlMaster failed with error: invalid resolved port returned: %s", b.String())
		}
		cd.listen_on = "tcp:localhost:" + strconv.Itoa(port)
	}
	term, err := tty.OpenControllingTerm(tty.SetNoEcho)
	if err != nil {
		return 1, fmt.Errorf("Failed to open controlling terminal with error: %w", err)
	}
	cd.echo_on = term.WasEchoOnOriginally()
	cd.host_opts, cd.literal_env = host_opts, literal_env
	cd.request_data = need_to_request_data
	cd.hostname_for_match, cd.username = hostname_for_match, uname
	escape_codes_to_set_colors, err := change_colors(cd.host_opts.Color_scheme)
	if err == nil {
		err = term.WriteAllString(escape_codes_to_set_colors + loop.SAVE_PRIVATE_MODE_VALUES + loop.HANDLE_TERMIOS_SIGNALS.EscapeCodeToSet())
	}
	if err != nil {
		return 1, err
	}
	restore_escape_codes := loop.RESTORE_PRIVATE_MODE_VALUES + loop.HANDLE_TERMIOS_SIGNALS.EscapeCodeToReset()
	if escape_codes_to_set_colors != "" {
		restore_escape_codes += "\x1b[#Q"
	}
	sigs := make(chan os.Signal, 8)
	signal.Notify(sigs, unix.SIGINT, unix.SIGTERM)
	cleaned_up := false
	cleanup := func() {
		if !cleaned_up {
			_ = term.WriteAllString(restore_escape_codes)
			term.RestoreAndClose()
			signal.Reset()
			cleaned_up = true
		}
	}
	defer cleanup()
	err = get_remote_command(&cd)
	if err != nil {
		return 1, err
	}
	cmd = append(cmd, cd.rcmd...)
	c := exec.Command(cmd[0], cmd[1:]...)
	c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
	err = c.Start()
	if err != nil {
		return 1, err
	}

	if !cd.request_data {
		rq := fmt.Sprintf("id=%s:pwfile=%s:pw=%s", cd.replacements["REQUEST_ID"], cd.replacements["PASSWORD_FILENAME"], cd.replacements["DATA_PASSWORD"])
		err := term.ApplyOperations(tty.TCSANOW, tty.SetNoEcho)
		if err == nil {
			var dcs string
			dcs, err = tui.DCSToKitty("ssh", rq)
			if err == nil {
				err = term.WriteAllString(dcs)
			}
		}
		if err != nil {
			_ = c.Process.Kill()
			_ = c.Wait()
			return 1, err
		}
	}
	go func() {
		<-sigs
		// ignore any interrupt and terminate signals as they will usually be sent to the ssh child process as well
		// and we are waiting on that.
	}()
	err = c.Wait()
	drain_potential_tty_garbage(term)
	if err != nil {
		var exit_err *exec.ExitError
		if errors.As(err, &exit_err) {
			if state := exit_err.ProcessState.String(); state == "signal: interrupt" {
				cleanup()
				_ = unix.Kill(os.Getpid(), unix.SIGINT)
				// Give the signal time to be delivered
				time.Sleep(20 * time.Millisecond)
			}
			return exit_err.ExitCode(), nil
		}
		return 1, err
	}
	return 0, nil
}

func main(cmd *cli.Command, o *Options, args []string) (rc int, err error) {
	if len(args) > 0 {
		switch args[0] {
		case "use-python":
			args = args[1:] // backwards compat from when we had a python implementation
		case "-h", "--help":
			cmd.ShowHelp()
			return
		}
	}
	ssh_args, server_args, passthrough, found_extra_args, err := ParseSSHArgs(args, "--kitten")
	if err != nil {
		var invargs *ErrInvalidSSHArgs
		switch {
		case errors.As(err, &invargs):
			if invargs.Msg != "" {
				fmt.Fprintln(os.Stderr, invargs.Msg)
			}
			return 1, unix.Exec(SSHExe(), []string{"ssh"}, os.Environ())
		}
		return 1, err
	}
	if passthrough {
		return 1, unix.Exec(SSHExe(), utils.Concat([]string{"ssh"}, ssh_args, server_args), os.Environ())
	}
	if os.Getenv("KITTY_WINDOW_ID") == "" || os.Getenv("KITTY_PID") == "" {
		return 1, fmt.Errorf("The SSH kitten is meant to run inside a kitty window")
	}
	if !tty.IsTerminal(os.Stdin.Fd()) {
		return 1, fmt.Errorf("The SSH kitten is meant for interactive use only, STDIN must be a terminal")
	}
	return run_ssh(ssh_args, server_args, found_extra_args)
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}

func specialize_command(ssh *cli.Command) {
	ssh.Usage = "arguments for the ssh command"
	ssh.ShortDescription = "Truly convenient SSH"
	ssh.HelpText = "The ssh kitten is a thin wrapper around the ssh command. It automatically enables shell integration on the remote host, re-uses existing connections to reduce latency, makes the kitty terminfo database available, etc. Its invocation is identical to the ssh command. For details on its usage, see :doc:`/kittens/ssh`."
	ssh.IgnoreAllArgs = true
	ssh.OnlyArgsAllowed = true
	ssh.ArgCompleter = cli.CompletionForWrapper("ssh")
}

func test_integration_with_python(args []string) (rc int, err error) {
	f, err := os.CreateTemp("", "*.conf")
	if err != nil {
		return 1, err
	}
	defer func() {
		f.Close()
		os.Remove(f.Name())
	}()
	_, err = io.Copy(f, os.Stdin)
	if err != nil {
		return 1, err
	}
	cd := &connection_data{
		request_id: "testing", remote_args: []string{},
		username: "testuser", hostname_for_match: "host.test", request_data: true,
		test_script: args[0], echo_on: true,
	}
	opts, bad_lines, err := load_config(cd.hostname_for_match, cd.username, nil, f.Name())
	if err == nil {
		if len(bad_lines) > 0 {
			return 1, fmt.Errorf("Bad config lines: %s with error: %s", bad_lines[0].Line, bad_lines[0].Err)
		}
		cd.host_opts = opts
		err = get_remote_command(cd)
	}
	if err != nil {
		return 1, err
	}
	data, err := json.Marshal(map[string]any{"cmd": cd.rcmd, "shm_name": cd.shm_name})
	if err == nil {
		_, err = os.Stdout.Write(data)
		os.Stdout.Close()
	}
	if err != nil {
		return 1, err
	}

	return
}

func TestEntryPoint(root *cli.Command) {
	root.AddSubCommand(&cli.Command{
		Name:            "ssh",
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return test_integration_with_python(args)
		},
	})

}
