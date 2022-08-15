package at

import (

	"github.com/spf13/cobra"

	"kitty/tools/cli"
	"kitty/tools/crypto"
)

var encrypt_cmd = crypto.Encrypt_cmd

func EntryPoint(tool_root *cobra.Command) *cobra.Command {
	var root = cli.CreateCommand(&cobra.Command{
		Use:   "@ [global options] command [command options] [command args]",
		Short: "Control kitty remotely",
		Long:  "Control kitty by sending it commands. Set the allow_remote_control option in kitty.conf or use a password, for this to work.",
	})
	root.Annotations["options_title"] = "Global options"

	root.PersistentFlags().String("password", "",
		"A password to use when contacting kitty. This will cause kitty to ask the user"+
			" for permission to perform the specified action, unless the password has been"+
			" accepted before or is pre-configured in :file:`kitty.conf`.")

	cli.PersistentChoices(root, "use-password", "If no password is available, kitty will usually just send the remote control command without a password. This option can be used to force it to always or never use the supplied password.", "if-available", "always", "never")
	return root
}
