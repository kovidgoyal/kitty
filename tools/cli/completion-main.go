// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
)

func json_input_parser(data []byte, shell_state map[string]string) ([][]string, error) {
	ans := make([][]string, 0, 32)
	err := json.Unmarshal(data, &ans)
	return ans, err
}

func json_output_serializer(completions []*Completions, shell_state map[string]string) ([]byte, error) {
	return json.Marshal(completions)
}

type completion_script_func func(commands []string) (string, error)
type parser_func func(data []byte, shell_state map[string]string) ([][]string, error)
type serializer_func func(completions []*Completions, shell_state map[string]string) ([]byte, error)

var completion_scripts = make(map[string]completion_script_func, 4)
var input_parsers = make(map[string]parser_func, 4)
var output_serializers = make(map[string]serializer_func, 4)
var init_completions = make(map[string]func(*Completions), 4)

func init() {
	input_parsers["json"] = json_input_parser
	output_serializers["json"] = json_output_serializer
}

var registered_exes []func(root *Command)

func RegisterExeForCompletion(x func(root *Command)) {
	if registered_exes == nil {
		registered_exes = make([]func(root *Command), 0, 4)
	}
	registered_exes = append(registered_exes, x)
}

func GenerateCompletions(args []string) error {
	output_type := "json"
	if len(args) > 0 {
		output_type = args[0]
		args = args[1:]
	}
	n := max(1, len(args))
	if output_type == "setup" {
		if len(args) == 0 {
			return fmt.Errorf("The shell must be specified")
		}
		shell_name := args[0]
		args = args[1:]
		completion_script := completion_scripts[shell_name]
		if completion_script == nil {
			return fmt.Errorf("Unsupported shell: %s", shell_name)
		}
		output, err := completion_script(args)
		if err == nil {
			_, err = os.Stdout.WriteString(output)
		}
		return err
	}
	shell_state := make(map[string]string, n)
	for _, arg := range args {
		k, v, found := strings.Cut(arg, "=")
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
	// debugf("%#v", string(data))
	all_argv, err := input_parser(data, shell_state)
	if err != nil {
		return err
	}
	var root = NewRootCommand()
	for _, re := range registered_exes {
		re(root)
	}

	err = root.Validate()
	if err != nil {
		return err
	}
	all_completions := make([]*Completions, 0, 1)
	for _, argv := range all_argv {
		all_completions = append(all_completions, root.GetCompletions(argv, init_completions[output_type]))
		root.ResetAfterParseArgs()
	}
	output, err := output_serializer(all_completions, shell_state)
	if err == nil {
		_, err = os.Stdout.Write(output)
	}
	return err
}
