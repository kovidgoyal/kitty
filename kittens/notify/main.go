package notify

import (
	"fmt"

	"kitty/tools/cli"
)

var _ = fmt.Print

func main(_ *cli.Command, opts_ *Options, args []string) (rc int, err error) {
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
