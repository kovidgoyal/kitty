// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package ask

import (
	"errors"
	"fmt"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tui"
)

var _ = fmt.Print

type Response struct {
	Items    []string `json:"items"`
	Response string   `json:"response"`
}

func show_message(msg string) {
	if msg != "" {
		m := markup.New(true)
		fmt.Println(m.Bold(msg))
	}
}

func main(_ *cli.Command, o *Options, args []string) (rc int, err error) {
	output := tui.KittenOutputSerializer()
	result := &Response{Items: args}
	if len(o.Prompt) > 2 && o.Prompt[0] == o.Prompt[len(o.Prompt)-1] && (o.Prompt[0] == '"' || o.Prompt[0] == '\'') {
		o.Prompt = o.Prompt[1 : len(o.Prompt)-1]
	}
	switch o.Type {
	case "yesno", "choices":
		result.Response, err = GetChoices(o)
		if err != nil {
			return 1, err
		}
	case "password":
		show_message(o.Message)
		pw, err := tui.ReadPassword(o.Prompt, false)
		if err != nil {
			if errors.Is(err, tui.Canceled) {
				pw = ""
			} else {
				return 1, err
			}
		}
		result.Response = pw
	case "line":
		show_message(o.Message)
		result.Response, err = get_line(o)
		if err != nil {
			return 1, err
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
