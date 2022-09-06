// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package completion

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/spf13/cobra"

	"kitty/tools/cli"
	"kitty/tools/utils"
)

func json_input_parser(data []byte, shell_state map[string]string) ([]string, error) {
	ans := make([]string, 0, 32)
	err := json.Unmarshal(data, &ans)
	return ans, err
}

func json_output_serializer(completions *Completions, shell_state map[string]string) ([]byte, error) {
	return json.Marshal(completions)
}

type parser_func func(data []byte, shell_state map[string]string) ([]string, error)
type serializer_func func(completions *Completions, shell_state map[string]string) ([]byte, error)

var input_parsers = make(map[string]parser_func, 4)
var output_serializers = make(map[string]serializer_func, 4)

func init() {
	input_parsers["json"] = json_input_parser
	output_serializers["json"] = json_output_serializer
}

func main(args []string) error {
	output_type := "json"
	if len(args) > 0 {
		output_type = args[0]
		args = args[1:]
	}
	shell_state := make(map[string]string, len(args))
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
	argv, err := input_parser(data, shell_state)
	if err != nil {
		return err
	}
	completions := GetCompletions(argv)
	output, err := output_serializer(completions, shell_state)
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
