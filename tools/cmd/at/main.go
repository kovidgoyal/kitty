package at

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/mattn/go-isatty"
	"github.com/spf13/cobra"
	"golang.org/x/sys/unix"
	"golang.org/x/term"

	"kitty"
	"kitty/tools/base85"
	"kitty/tools/cli"
	"kitty/tools/crypto"
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
	ans, err = json.Marshal(rc)
	return
}

type serializer_func func(rc *utils.RemoteControlCmd) ([]byte, error)

var serializer serializer_func = simple_serializer

func create_serializer(password string, encoded_pubkey string, response_timeout float64) (ans serializer_func, timeout float64, err error) {
	timeout = response_timeout
	if password != "" {
		encryption_version, pubkey, err := get_pubkey(encoded_pubkey)
		if err != nil {
			return nil, timeout, err
		}
		ans = func(rc *utils.RemoteControlCmd) (ans []byte, err error) {
			ec, err := crypto.Encrypt_cmd(rc, global_options.password, pubkey, encryption_version)
			ans, err = json.Marshal(ec)
			return
		}
		if timeout < 120 {
			timeout = 120
		}
		return ans, timeout, nil
	}
	return simple_serializer, timeout, nil
}

type TTYIO interface {
	WriteAllWithTimeout(b []byte, d time.Duration) (n int, err error)
	WriteFromReader(r utils.Reader, read_timeout time.Duration, write_timeout time.Duration) (n int, err error)
	ReadWithTimeout(b []byte, d time.Duration) (n int, err error)

	Restore() error
	Close() error
}

func do_tty_io(tty TTYIO, input utils.Reader, no_response bool, response_timeout time.Duration) (serialized_response []byte, err error) {

	_, err = tty.WriteAllWithTimeout([]byte("\x1bP@kitty-cmd"), 2*time.Second)
	if err != nil {
		return
	}
	_, err = tty.WriteFromReader(input, 2*time.Second, 2*time.Second)
	if err != nil {
		return
	}
	_, err = tty.WriteAllWithTimeout([]byte("\x1b\\"), 2*time.Second)
	if err != nil {
		return
	}
	if no_response {
		return
	}

	response_received := false
	cmd_prefix := []byte("@kitty-cmd")

	handle_dcs := func(b []byte) {
		if bytes.HasPrefix(b, cmd_prefix) {
			response_received = true
		}
		serialized_response = b[len(cmd_prefix):]
	}

	var p utils.EscapeCodeParser = utils.EscapeCodeParser{HandleDCS: handle_dcs}
	buf := make([]byte, 0, utils.DEFAULT_IO_BUFFER_SIZE)

	for !response_received {
		buf = buf[:cap(buf)]
		var n int
		n, err = tty.ReadWithTimeout(buf, response_timeout)
		if err != nil {
			if err == os.ErrDeadlineExceeded {
				err = fmt.Errorf("Timed out while waiting for a response from kitty")
			}
			return
		}
		buf = buf[:n]
		p.Parse(buf)
	}
	return
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

func get_response(rc *utils.RemoteControlCmd, timeout float64) (ans *Response, err error) {
	serializer, timeout, err = create_serializer(global_options.password, "", timeout)
	if err != nil {
		return
	}
	d, err := serializer(rc)
	if err != nil {
		return
	}
	var tty TTYIO
	if global_options.to_network == "" {
		tty, err = utils.OpenControllingTerm(true)
		if err != nil {
			return
		}
	} else {
		err = fmt.Errorf("TODO: Implement socket IO")
		return
	}
	defer func() {
		tty.Restore()
		tty.Close()
	}()
	r := utils.BytesReader{Data: d}
	serialized_response, err := do_tty_io(tty, &r, rc.NoResponse, time.Duration(timeout*float64(time.Second)))
	if err != nil {
		if err == os.ErrDeadlineExceeded {
			rc.Payload = nil
			rc.CancelAsync = true
			rc.NoResponse = true
			d, err = serializer(rc)
			if err != nil {
				return
			}
			_, err = do_tty_io(tty, &r, rc.NoResponse, 0)
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

func send_rc_command(rc *utils.RemoteControlCmd, timeout float64, string_response_is_err bool) (err error) {
	response, err := get_response(rc, timeout)
	if err != nil || response == nil {
		return err
	}
	if !response.Ok {
		if response.Traceback != "" {
			fmt.Fprintln(os.Stderr, response.Traceback)
		}
		return fmt.Errorf("%s", response.Error)
	}
	if response.Data.is_string && string_response_is_err {
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
			if isatty.IsTerminal(os.Stdin.Fd()) {
				q, err := term.ReadPassword(int(os.Stdin.Fd()))
				if err != nil {
					ans = string(q)
				}
			} else {
				q, err := io.ReadAll(os.Stdin)
				if err != nil {
					ans = strings.TrimRight(string(q), " \n\t")
				}
				ttyf, err := os.Open("/dev/tty")
				if err != nil {
					err = unix.Dup2(int(ttyf.Fd()), int(os.Stdin.Fd()))
					ttyf.Close()
				}
			}
		} else {
			q, err := os.ReadFile(password_file)
			if err != nil {
				ans = strings.TrimRight(string(q), " \n\t")
			}
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

func EntryPoint(tool_root *cobra.Command) *cobra.Command {
	var at_root_command *cobra.Command
	var to, password, password_file, password_env *string
	var use_password *cli.ChoicesVal
	at_root_command = cli.CreateCommand(&cobra.Command{
		Use:   "@ [global options] command [command options] [command args]",
		Short: "Control kitty remotely",
		Long:  "Control kitty by sending it commands. Set the allow_remote_control option in :file:`kitty.conf` or use a password, for this to work.",
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			if *to == "" {
				*to = os.Getenv("KITTY_LISTEN_ON")
				global_options.to_address_is_from_env_var = true
			}
			if *to != "" {
				network, address, err := utils.ParseSocketAddress(*to)
				if err != nil {
					return err
				}
				global_options.to_network = network
				global_options.to_address = address
			}
			q, err := get_password(*password, *password_file, *password_env, use_password.Choice)
			global_options.password = q
			return err
		},
	})
	at_root_command.Annotations["options_title"] = "Global options"
	fs := at_root_command.PersistentFlags()

	to = fs.String("to", "",
		"An address for the kitty instance to control. Corresponds to the address given"+
			" to the kitty instance via the :option:`kitty --listen-on` option or the :opt:`listen_on` setting in :file:`kitty.conf`. If not"+
			" specified, the environment variable :envvar:`KITTY_LISTEN_ON` is checked. If that"+
			" is also not found, messages are sent to the controlling terminal for this"+
			" process, i.e. they will only work if this process is run within a kitty window.")

	password = fs.String("password", "",
		"A password to use when contacting kitty. This will cause kitty to ask the user"+
			" for permission to perform the specified action, unless the password has been"+
			" accepted before or is pre-configured in :file:`kitty.conf`.")

	password_file = fs.String("password-file", "rc-pass",
		"A file from which to read the password. Trailing whitespace is ignored. Relative"+
			" paths are resolved from the kitty configuration directory. Use - to read from STDIN."+
			" Used if no :option:`--password` is supplied. Defaults to checking for the"+
			" :file:`rc-pass` file in the kitty configuration directory.")

	password_env = fs.String("password-env", "KITTY_RC_PASSWORD",
		"The name of an environment variable to read the password from."+
			" Used if no :option:`--password-file` or :option:`--password` is supplied.")

	use_password = cli.Choices(fs, "use-password", "If no password is available, kitty will usually just send the remote control command without a password. This option can be used to force it to always or never use the supplied password.", "if-available", "always", "never")

	for cmd_name, reg_func := range all_commands {
		c := reg_func(at_root_command)
		at_root_command.AddCommand(c)
		command_objects[cmd_name] = c
		alias := *c
		alias.Use = "@" + alias.Use
		alias.Hidden = true
		tool_root.AddCommand(&alias)
	}
	return at_root_command
}
