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
	"strings"
	"time"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
	"golang.org/x/sys/unix"

	"github.com/jamesruan/go-rfc1924/base85"
	"kitty"
	"kitty/tools/cli"
	"kitty/tools/crypto"
	"kitty/tools/tty"
	"kitty/tools/tui"
	"kitty/tools/utils"
)

var ProtocolVersion [3]int = [3]int{0, 20, 0}

func add_bool_set(cmd *cobra.Command, name string, short string, usage string) *bool {
	if short == "" {
		return cmd.Flags().Bool(name, false, usage)
	}
	return cmd.Flags().BoolP(name, short, false, usage)
}

type GlobalOptions struct {
	to_network, to_address, password string
	to_address_is_from_env_var       bool
}

var global_options GlobalOptions

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
	encryption_version, encoded_key, found := utils.Cut(encoded_key, ":")
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

func simple_serializer(rc *utils.RemoteControlCmd) (ans []byte, err error) {
	return json.Marshal(rc)
}

type serializer_func func(rc *utils.RemoteControlCmd) ([]byte, error)

type wrapped_serializer struct {
	state             int
	serializer        serializer_func
	all_payloads_done bool
}

func debug_to_log(args ...interface{}) {
	f, err := os.OpenFile("/tmp/kdlog", os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0666)
	if err == nil {
		fmt.Fprintln(f, args...)
		f.Close()
	}
}

func (self *wrapped_serializer) next(io_data *rc_io_data) ([]byte, error) {
	const prefix = "\x1bP@kitty-cmd"
	const suffix = "\x1b\\"
	switch self.state {
	case 0:
		self.state++
		return []byte(prefix), nil
	case 1:
		if io_data.multiple_payload_generator != nil {
			is_last, err := io_data.multiple_payload_generator(io_data)
			if err != nil {
				return nil, err
			}
			if is_last {
				self.all_payloads_done = true
			}
		} else {
			self.all_payloads_done = true
		}
		self.state++
		return self.serializer(io_data.rc)
	case 2:
		if self.all_payloads_done {
			self.state++
		} else {
			self.state = 0
		}
		return []byte(suffix), nil
	default:
		return make([]byte, 0), nil
	}
}

var serializer serializer_func = simple_serializer

func create_serializer(password string, encoded_pubkey string, io_data *rc_io_data) (err error) {
	io_data.serializer.serializer = simple_serializer
	if password != "" {
		encryption_version, pubkey, err := get_pubkey(encoded_pubkey)
		if err != nil {
			return err
		}
		io_data.serializer.serializer = func(rc *utils.RemoteControlCmd) (ans []byte, err error) {
			ec, err := crypto.Encrypt_cmd(rc, global_options.password, pubkey, encryption_version)
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
	cmd                        *cobra.Command
	rc                         *utils.RemoteControlCmd
	serializer                 wrapped_serializer
	send_keypresses            bool
	string_response_is_err     bool
	timeout                    time.Duration
	multiple_payload_generator func(io_data *rc_io_data) (bool, error)
}

func (self *rc_io_data) next_chunk() (chunk []byte, one_escape_code_done bool, err error) {
	one_escape_code_done = self.serializer.state == 2
	block, err := self.serializer.next(self)
	if err != nil && !errors.Is(err, io.EOF) {
		return
	}
	err = nil
	chunk = block
	return
}

func get_response(do_io func(io_data *rc_io_data) ([]byte, error), io_data *rc_io_data) (ans *Response, err error) {
	serialized_response, err := do_io(io_data)
	if err != nil {
		if errors.Is(err, os.ErrDeadlineExceeded) {
			io_data.rc.Payload = nil
			io_data.rc.CancelAsync = true
			io_data.multiple_payload_generator = nil
			io_data.rc.NoResponse = true
			io_data.serializer.state = 0
			do_io(io_data)
			err = fmt.Errorf("Timed out waiting for a response from kitty")
		}
		return
	}
	if len(serialized_response) == 0 {
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

func send_rc_command(io_data *rc_io_data) (err error) {
	err = setup_global_options(io_data.cmd)
	if err != nil {
		return err
	}
	err = create_serializer(global_options.password, "", io_data)
	if err != nil {
		return
	}
	var response *Response
	if global_options.to_network == "" {
		response, err = get_response(do_tty_io, io_data)
		if err != nil {
			return
		}
	} else {
		response, err = get_response(do_socket_io, io_data)
		if err != nil {
			return
		}
	}
	if err != nil || response == nil {
		return err
	}
	if !response.Ok {
		if response.Traceback != "" {
			fmt.Fprintln(os.Stderr, response.Traceback)
		}
		return fmt.Errorf("%s", response.Error)
	}
	if response.Data.is_string && io_data.string_response_is_err {
		return fmt.Errorf("%s", response.Data.as_str)
	}
	fmt.Println(strings.TrimRight(response.Data.as_str, "\n \t"))
	return
}

func get_password(password string, password_file string, password_env string, use_password string) (ans string, err error) {
	if use_password == "never" {
		return
	}
	if password != "" {
		ans = password
	}
	if ans == "" && password_file != "" {
		if password_file == "-" {
			if tty.IsTerminal(os.Stdin.Fd()) {
				ans, err = tui.ReadPassword("Password: ", true)
				if err != nil {
					return
				}
			} else {
				var q []byte
				q, err = io.ReadAll(os.Stdin)
				if err == nil {
					ans = strings.TrimRight(string(q), " \n\t")
				}
				ttyf, err := os.Open(tty.Ctermid())
				if err == nil {
					err = unix.Dup2(int(ttyf.Fd()), int(os.Stdin.Fd()))
					ttyf.Close()
				}
			}
		} else {
			var q []byte
			q, err = os.ReadFile(password_file)
			if err == nil {
				ans = strings.TrimRight(string(q), " \n\t")
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
	if ans == "" && password_env != "" {
		ans = os.Getenv(password_env)
	}
	if ans == "" && use_password == "always" {
		return ans, fmt.Errorf("No password was found")
	}
	if len(ans) > 1024 {
		return ans, fmt.Errorf("Specified password is too long")
	}
	return ans, nil
}

var all_commands map[string]func(*cobra.Command) *cobra.Command = make(map[string]func(*cobra.Command) *cobra.Command)
var command_objects map[string]*cobra.Command = make(map[string]*cobra.Command)

func add_global_options(fs *pflag.FlagSet) {
	fs.String("to", "",
		"An address for the kitty instance to control. Corresponds to the address given"+
			" to the kitty instance via the :option:`kitty --listen-on` option or the :opt:`listen_on` setting in :file:`kitty.conf`. If not"+
			" specified, the environment variable :envvar:`KITTY_LISTEN_ON` is checked. If that"+
			" is also not found, messages are sent to the controlling terminal for this"+
			" process, i.e. they will only work if this process is run within a kitty window.")

	fs.String("password", "",
		"A password to use when contacting kitty. This will cause kitty to ask the user"+
			" for permission to perform the specified action, unless the password has been"+
			" accepted before or is pre-configured in :file:`kitty.conf`.")

	fs.String("password-file", "rc-pass",
		"A file from which to read the password. Trailing whitespace is ignored. Relative"+
			" paths are resolved from the kitty configuration directory. Use - to read from STDIN."+
			" Used if no :option:`--password` is supplied. Defaults to checking for the"+
			" :file:`rc-pass` file in the kitty configuration directory.")

	fs.String("password-env", "KITTY_RC_PASSWORD",
		"The name of an environment variable to read the password from."+
			" Used if no :option:`--password-file` or :option:`--password` is supplied.")

	cli.Choices(fs, "use-password", "If no password is available, kitty will usually just send the remote control command without a password. This option can be used to force it to always or never use the supplied password.", "if-available", "always", "never")

}

func setup_global_options(cmd *cobra.Command) (err error) {
	var v = cli.FlagValGetter{Flags: cmd.Flags()}
	to := v.String("to")
	password := v.String("password")
	password_file := v.String("password-file")
	password_env := v.String("password-env")
	use_password := v.String("use-password")
	if v.Err != nil {
		return v.Err
	}
	if to == "" {
		to = os.Getenv("KITTY_LISTEN_ON")
		global_options.to_address_is_from_env_var = true
	}
	if to != "" {
		network, address, err := utils.ParseSocketAddress(to)
		if err != nil {
			return err
		}
		global_options.to_network = network
		global_options.to_address = address
	}
	q, err := get_password(password, password_file, password_env, use_password)
	global_options.password = q
	return err

}

func EntryPoint(tool_root *cobra.Command) *cobra.Command {
	at_root_command := cli.CreateCommand(&cobra.Command{
		Use:   "@ [global options] command [command options] [command args]",
		Short: "Control kitty remotely",
		Long:  "Control kitty by sending it commands. Set the allow_remote_control option in :file:`kitty.conf` or use a password, for this to work.",
	})
	at_root_command.Annotations["options_title"] = "Global options"
	add_global_options(at_root_command.PersistentFlags())

	for cmd_name, reg_func := range all_commands {
		c := reg_func(at_root_command)
		at_root_command.AddCommand(c)
		command_objects[cmd_name] = c
		alias := *c
		alias.Use = "@" + alias.Use
		alias.Hidden = true
		add_global_options(alias.Flags())
		tool_root.AddCommand(&alias)
	}
	return at_root_command
}
