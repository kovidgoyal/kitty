// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/spf13/cobra"

	"kitty/tools/cli"
	"kitty/tools/tty"
	"kitty/tools/utils"
)

func debug(args ...interface{}) {
	tty.DebugPrintln(args...)
}

func debugf(format string, args ...interface{}) {
	debug(fmt.Sprintf(format, args...))
}

func json_input_parser(data []byte, shell_state map[string]string) ([][]string, error) {
	ans := make([][]string, 0, 32)
	err := json.Unmarshal(data, &ans)
	return ans, err
}

func json_output_serializer(completions []*Completions, shell_state map[string]string) ([]byte, error) {
	return json.Marshal(completions)
}

type parser_func func(data []byte, shell_state map[string]string) ([][]string, error)
type serializer_func func(completions []*Completions, shell_state map[string]string) ([]byte, error)

var input_parsers = make(map[string]parser_func, 4)
var output_serializers = make(map[string]serializer_func, 4)
var init_completions = make(map[string]func(*Completions), 4)

func init() {
	input_parsers["json"] = json_input_parser
	output_serializers["json"] = json_output_serializer
}

var registered_exes = make(map[string]func(root *Command))

func main(args []string) error {
	output_type := "json"
	if len(args) > 0 {
		output_type = args[0]
		args = args[1:]
	}
	n := len(args)
	if n < 1 {
		n = 1
	}
	shell_state := make(map[string]string, n)
	for _, arg := range args {
		k, v, found := utils.Cut(arg, "=")
		if !found {
			return fmt.Errorf("Invalid shell state specification: %s", arg)
		}
		shell_state[k] = v
	}
	input_parser := input_parsers[output_type]
	output_serializer := output_serializers[output_type]
	if input_parser == nil || output_serializer == nil {
		return fmt.Errorf("Unknown output type: %s", output_type)
	}
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		return err
	}
	all_argv, err := input_parser(data, shell_state)
	if err != nil {
		return err
	}
	var root = Command{Options: make([]*Option, 0), Groups: make([]*CommandGroup, 0, 8)}
	for _, re := range registered_exes {
		re(&root)
	}

	all_completions := make([]*Completions, 0, 1)
	for _, argv := range all_argv {
		all_completions = append(all_completions, root.GetCompletions(argv, init_completions[output_type]))
	}
	output, err := output_serializer(all_completions, shell_state)
	if err == nil {
		_, err = os.Stdout.Write(output)
	}
	return err
}

func EntryPoint(tool_root *cobra.Command) *cobra.Command {
	complete_command := cli.CreateCommand(&cobra.Command{
		Use:    "__complete__ output_type [shell state...]",
		Short:  "Generate completions for kitty commands",
		Long:   "Generate completion candidates for kitty commands. The command line is read from STDIN. output_type can be one of the supported  shells or 'json' for JSON output.",
		Hidden: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			return main(args)
		},
	})
	return complete_command
}
