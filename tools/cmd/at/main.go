// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package at

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"reflect"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty"
	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/crypto"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/utils"
	"github.com/kovidgoyal/kitty/tools/utils/base85"
	"github.com/kovidgoyal/kitty/tools/utils/shlex"
)

const lowerhex = "0123456789abcdef"

var ProtocolVersion [3]int = [3]int{0, 26, 0}

type password struct {
	val    string
	is_set bool
}

type GlobalOptions struct {
	to_network, to_address     string
	password                   password
	to_address_is_from_env_var bool
	already_setup              bool
}

var global_options GlobalOptions

func expand_ansi_c_escapes_in_args(args ...string) (escaped_string, error) {
	for i, x := range args {
		args[i] = shlex.ExpandANSICEscapes(x)
	}
	return escaped_string(strings.Join(args, " ")), nil
}

func escape_list_of_strings(args []string) []escaped_string {
	ans := make([]escaped_string, len(args))
	for i, x := range args {
		ans[i] = escaped_string(x)
	}
	return ans
}

func set_payload_string_field(io_data *rc_io_data, field, data string) {
	payload_interface := reflect.ValueOf(&io_data.rc.Payload).Elem()
	struct_in_interface := reflect.New(payload_interface.Elem().Type()).Elem()
	struct_in_interface.Set(payload_interface.Elem()) // copies the payload to struct_in_interface
	struct_in_interface.FieldByName(field).SetString(data)
	payload_interface.Set(struct_in_interface) // copies struct_in_interface back to payload
}

func get_pubkey(encoded_key string) (encryption_version string, pubkey []byte, err error) {
	if encoded_key == "" {
		encoded_key = os.Getenv("KITTY_PUBLIC_KEY")
		if encoded_key == "" {
			err = fmt.Errorf("Password usage requested but KITTY_PUBLIC_KEY environment variable is not available")
			return
		}
	}
	encryption_version, encoded_key, found := strings.Cut(encoded_key, ":")
	if !found {
		err = fmt.Errorf("KITTY_PUBLIC_KEY environment variable does not have a : in it")
		return
	}
	if encryption_version != kitty.RC_ENCRYPTION_PROTOCOL_VERSION {
		err = fmt.Errorf("KITTY_PUBLIC_KEY has unknown version, if you are running on a remote system, update kitty on this system")
		return
	}
	pubkey = make([]byte, base85.DecodedLen(len(encoded_key)))
	n, err := base85.Decode(pubkey, []byte(encoded_key))
	if err == nil {
		pubkey = pubkey[:n]
	}
	return
}

type escaped_string string

func (s escaped_string) MarshalJSON() ([]byte, error) {
	// See https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON
	// we additionally escape all non-ascii chars so they can be safely transmitted inside an escape code
	src := utf16.Encode([]rune(s))
	buf := make([]byte, 0, len(src)+128)
	a := func(x ...byte) {
		buf = append(buf, x...)
	}
	a('"')
	for _, r := range src {
		if ' ' <= r && r <= 126 {
			if r == '\\' || r == '"' {
				buf = append(buf, '\\')
			}
			buf = append(buf, byte(r))
			continue
		}
		switch r {
		case '\n':
			a('\\', 'n')
		case '\t':
			a('\\', 't')
		case '\r':
			a('\\', 'r')
		case '\f':
			a('\\', 'f')
		case '\b':
			a('\\', 'b')
		default:
			a('\\', 'u')
			for s := 12; s >= 0; s -= 4 {
				a(lowerhex[r>>uint(s)&0xF])
			}
		}
	}
	a('"')
	return buf, nil
}

func simple_serializer(rc *utils.RemoteControlCmd) (ans []byte, err error) {
	return json.Marshal(rc)
}

type serializer_func func(rc *utils.RemoteControlCmd) ([]byte, error)

func create_serializer(password password, encoded_pubkey string, io_data *rc_io_data) (err error) {
	io_data.serializer = simple_serializer
	if password.is_set {
		encryption_version, pubkey, err := get_pubkey(encoded_pubkey)
		if err != nil {
			return err
		}
		io_data.serializer = func(rc *utils.RemoteControlCmd) (ans []byte, err error) {
			ec, err := crypto.Encrypt_cmd(rc, global_options.password.val, pubkey, encryption_version)
			if err != nil {
				return
			}
			return json.Marshal(ec)
		}
		if io_data.timeout < 120*time.Second {
			io_data.timeout = 120 * time.Second
		}
	}
	return nil
}

type ResponseData struct {
	as_str    string
	is_string bool
}

func (self *ResponseData) UnmarshalJSON(data []byte) error {
	if bytes.HasPrefix(data, []byte("\"")) {
		self.is_string = true
		return json.Unmarshal(data, &self.as_str)
	}
	if bytes.Equal(data, []byte("true")) {
		self.as_str = "True"
	} else if bytes.Equal(data, []byte("false")) {
		self.as_str = "False"
	} else {
		self.as_str = string(data)
	}
	return nil
}

type Response struct {
	Ok        bool         `json:"ok"`
	Data      ResponseData `json:"data,omitempty"`
	Error     string       `json:"error,omitempty"`
	Traceback string       `json:"tb,omitempty"`
}

type rc_io_data struct {
	cmd                        *cli.Command
	rc                         *utils.RemoteControlCmd
	serializer                 serializer_func
	on_key_event               func(lp *loop.Loop, ke *loop.KeyEvent) error
	string_response_is_err     bool
	handle_response            func(data []byte) error
	timeout                    time.Duration
	multiple_payload_generator func(io_data *rc_io_data) (bool, error)

	chunks_done bool
}

func (self *rc_io_data) next_chunk() (chunk []byte, err error) {
	if self.chunks_done {
		return make([]byte, 0), nil
	}
	if self.multiple_payload_generator != nil {
		is_last, err := self.multiple_payload_generator(self)
		if err != nil {
			return nil, err
		}
		if is_last {
			self.chunks_done = true
		}
		return self.serializer(self.rc)
	}
	self.chunks_done = true
	return self.serializer(self.rc)
}

func get_response(do_io func(io_data *rc_io_data) ([]byte, error), io_data *rc_io_data) (ans *Response, err error) {
	serialized_response, err := do_io(io_data)
	if err != nil {
		if errors.Is(err, os.ErrDeadlineExceeded) && io_data.rc.Async != "" {
			io_data.rc.Payload = nil
			io_data.rc.CancelAsync = true
			io_data.multiple_payload_generator = nil
			io_data.rc.NoResponse = true
			io_data.chunks_done = false
			_, _ = do_io(io_data)
			err = fmt.Errorf("Timed out waiting for a response from kitty")
		}
		return nil, err
	}
	if len(serialized_response) == 0 {
		if io_data.rc.NoResponse {
			res := Response{Ok: true}
			ans = &res
			return
		}
		err = fmt.Errorf("Received empty response from kitty")
		return
	}
	var response Response
	err = json.Unmarshal(serialized_response, &response)
	if err != nil {
		err = fmt.Errorf("Invalid response received from kitty, unmarshalling error: %w", err)
		return
	}
	ans = &response
	return
}

var running_shell = false

type exit_error struct {
	exit_code int
}

func (m *exit_error) Error() string {
	return fmt.Sprintf("Subprocess exit with code: %d", m.exit_code)
}

func send_rc_command(io_data *rc_io_data) (err error) {
	err = setup_global_options(io_data.cmd)
	if err != nil {
		return err
	}
	wid, err := strconv.Atoi(os.Getenv("KITTY_WINDOW_ID"))
	if err == nil && wid > 0 {
		io_data.rc.KittyWindowId = uint(wid)
	}
	err = create_serializer(global_options.password, "", io_data)
	if err != nil {
		return
	}
	var response *Response
	response, err = get_response(utils.IfElse(global_options.to_network == "", do_tty_io, do_socket_io), io_data)
	if err != nil || response == nil {
		return
	}
	if !response.Ok {
		if response.Traceback != "" {
			fmt.Fprintln(os.Stderr, response.Traceback)
		}
		return fmt.Errorf("%s", response.Error)
	}
	if io_data.handle_response != nil {
		return io_data.handle_response(utils.UnsafeStringToBytes(response.Data.as_str))
	}
	if response.Data.is_string && io_data.string_response_is_err {
		return fmt.Errorf("%s", response.Data.as_str)
	}
	if response.Data.as_str != "" {
		fmt.Println(strings.TrimRight(response.Data.as_str, "\n \t"))
	}
	return
}

func get_password(password string, password_file string, password_env string, use_password string) (ans password, err error) {
	if use_password == "never" {
		return
	}
	if password != "" {
		ans.is_set, ans.val = true, password
	}
	if !ans.is_set && password_file != "" {
		if password_file == "-" {
			if tty.IsTerminal(os.Stdin.Fd()) {
				p, err := tui.ReadPassword("Password: ", true)
				if err != nil {
					return ans, err
				}
				ans.is_set, ans.val = true, p
			} else {
				var q []byte
				q, err = io.ReadAll(os.Stdin)
				if err == nil {
					ans.is_set, ans.val = true, strings.TrimRight(string(q), " \n\t")
				}
				ttyf, err := os.Open(tty.Ctermid())
				if err == nil {
					err = unix.Dup2(int(ttyf.Fd()), int(os.Stdin.Fd())) //nolint ineffassign err is returned indicating duping failed
					ttyf.Close()
				}
			}
		} else if strings.HasPrefix(password_file, "fd:") {
			var fd int
			if fd, err = strconv.Atoi(password_file[3:]); err == nil {
				f := os.NewFile(uintptr(fd), password_file)
				var q []byte
				if q, err = io.ReadAll(f); err == nil {
					ans.is_set = true
					ans.val = string(q)
				}
				f.Close()
			}
		} else {
			var q []byte
			q, err = os.ReadFile(password_file)
			if err == nil {
				ans.is_set, ans.val = true, strings.TrimRight(string(q), " \n\t")
			} else {
				if errors.Is(err, os.ErrNotExist) {
					err = nil
				}
			}
		}
		if err != nil {
			return
		}
	}
	if !ans.is_set && password_env != "" {
		ans.val, ans.is_set = os.LookupEnv(password_env)
	}
	if !ans.is_set && use_password == "always" {
		ans.is_set = true
		return ans, nil
	}
	if len(ans.val) > 1024 {
		return ans, fmt.Errorf("Specified password is too long")
	}
	return ans, nil
}

var all_commands []func(*cli.Command) *cli.Command = make([]func(*cli.Command) *cli.Command, 0, 64)

func register_at_cmd(f func(*cli.Command) *cli.Command) {
	all_commands = append(all_commands, f)
}

func setup_global_options(cmd *cli.Command) (err error) {
	if global_options.already_setup {
		return nil
	}
	err = cmd.GetOptionValues(&rc_global_opts)
	if err != nil {
		return err
	}
	if rc_global_opts.To == "" {
		rc_global_opts.To = os.Getenv("KITTY_LISTEN_ON")
		global_options.to_address_is_from_env_var = true
	}
	if rc_global_opts.To != "" {
		network, address, err := utils.ParseSocketAddress(rc_global_opts.To)
		if err != nil {
			return err
		}
		global_options.to_network = network
		global_options.to_address = address
	}
	q, err := get_password(rc_global_opts.Password, rc_global_opts.PasswordFile, rc_global_opts.PasswordEnv, rc_global_opts.UsePassword)
	global_options.password = q
	global_options.already_setup = true
	return err

}

func EntryPoint(tool_root *cli.Command) *cli.Command {
	at_root_command := tool_root.AddSubCommand(&cli.Command{
		Name:             "@",
		Usage:            "[global options] [sub-command] [sub-command options] [sub-command args]",
		ShortDescription: "Control kitty remotely",
		HelpText:         "Control kitty by sending it commands. Set the allow_remote_control option in :file:`kitty.conf` for this to work. When run without any sub-commands this will start an interactive shell to control kitty.",
		Run:              shell_main,
	})
	add_rc_global_opts(at_root_command)

	global_options_group := at_root_command.OptionGroups[0]

	for _, reg_func := range all_commands {
		c := reg_func(at_root_command)
		clone := tool_root.AddClone("", c)
		clone.Name = "@" + c.Name
		clone.Hidden = true
		clone.OptionGroups = append(clone.OptionGroups, global_options_group.Clone(clone))
	}
	return at_root_command
}
