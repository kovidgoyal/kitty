// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ask

import (
	"fmt"

	"kitty/tools/cli"
	"kitty/tools/tui"
)

var _ = fmt.Print

func main(_ *cli.Command, o *Options, args []string) (rc int, err error) {
	output := tui.KittenOutputSerializer()
	var result any
	if len(o.Prompt) > 2 && o.Prompt[0] == o.Prompt[len(o.Prompt)-1] && (o.Prompt[0] == '"' || o.Prompt[0] == '\'') {
		o.Prompt = o.Prompt[1 : len(o.Prompt)-1]
	}
	switch o.Type {
	case "yesno", "choices":
		result, err = choices(o, args)
		if err != nil {
			return rc, err
		}
	case "password":
		result, err = tui.ReadPassword(o.Prompt, true)
		if err != nil {
			return rc, err
		}
	default:
		return 1, fmt.Errorf("Unknown type: %s", o.Type)
	}
	s, err := output(result)
	if err != nil {
		return 1, err
	}
	_, err = fmt.Println(s)
	if err != nil {
		return 1, err
	}
	return
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
