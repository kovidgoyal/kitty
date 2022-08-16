package at

import (
	"fmt"
	"io/ioutil"
	"os"
	"strings"

	"github.com/mattn/go-isatty"
	"github.com/spf13/cobra"
	"golang.org/x/sys/unix"
	"golang.org/x/term"

	"kitty/tools/cli"
	"kitty/tools/crypto"
)

var encrypt_cmd = crypto.Encrypt_cmd

type GlobalOptions struct {
	to, password, use_password string
	to_from_env                bool
}

var global_options GlobalOptions

func get_password(password string, password_file string, password_env string, use_password string) (string, error) {
	if use_password == "never" {
		return "", nil
	}
	ans := ""
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
				q, err := ioutil.ReadAll(os.Stdin)
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
			q, err := ioutil.ReadFile(password_file)
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

func EntryPoint(tool_root *cobra.Command) *cobra.Command {
	var to, password, password_file, password_env, use_password *string
	var root = cli.CreateCommand(&cobra.Command{
		Use:   "@ [global options] command [command options] [command args]",
		Short: "Control kitty remotely",
		Long:  "Control kitty by sending it commands. Set the allow_remote_control option in :file:`kitty.conf` or use a password, for this to work.",
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			if *to == "" {
				*to = os.Getenv("KITTY_LISTEN_ON")
				global_options.to_from_env = true
			}
			global_options.to = *to
			global_options.use_password = *use_password
			q, err := get_password(*password, *password_file, *password_env, *use_password)
			global_options.password = q
			return err
		},
	})
	root.Annotations["options_title"] = "Global options"

	to = root.PersistentFlags().String("to", "",
		"An address for the kitty instance to control. Corresponds to the address given"+
			" to the kitty instance via the :option:`kitty --listen-on` option or the :opt:`listen_on` setting in :file:`kitty.conf`. If not"+
			" specified, the environment variable :envvar:`KITTY_LISTEN_ON` is checked. If that"+
			" is also not found, messages are sent to the controlling terminal for this"+
			" process, i.e. they will only work if this process is run within a kitty window.")

	password = root.PersistentFlags().String("password", "",
		"A password to use when contacting kitty. This will cause kitty to ask the user"+
			" for permission to perform the specified action, unless the password has been"+
			" accepted before or is pre-configured in :file:`kitty.conf`.")

	password_file = root.PersistentFlags().String("password-file", "rc-pass",
		"A file from which to read the password. Trailing whitespace is ignored. Relative"+
			" paths are resolved from the kitty configuration directory. Use - to read from STDIN."+
			" Used if no :option:`--password` is supplied. Defaults to checking for the"+
			" :file:`rc-pass` file in the kitty configuration directory.")

	password_env = root.PersistentFlags().String("password-env", "KITTY_RC_PASSWORD",
		"The name of an environment variable to read the password from."+
			" Used if no :option:`--password-file` or :option:`--password` is supplied.")

	use_password = cli.PersistentChoices(root, "use-password", "If no password is available, kitty will usually just send the remote control command without a password. This option can be used to force it to always or never use the supplied password.", "if-available", "always", "never")
	return root
}
