// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package cli

import (
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/google/shlex"
)

var _ = fmt.Print

type options struct {
	SimpleString string
	Choices      string
	FromParent   int
	SetMe        bool
	Int          int
	Float        float64
}

func TestCLIParsing(t *testing.T) {

	rt := func(expected_cmd *Command, cmdline string, expected_options any, expected_args ...string) {
		cp, err := shlex.Split(cmdline)
		if err != nil {
			t.Fatal(err)
		}
		cmd, err := expected_cmd.ParseArgs(cp)
		if err != nil {
			t.Fatal(err)
		}
		actual_options := reflect.New(reflect.TypeOf(expected_options).Elem()).Interface()
		err = cmd.GetOptionValues(actual_options)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(expected_options, actual_options) {
			t.Fatalf("Option values incorrect (expected != actual):\nCommand line: %s\n%#v != %#v", cmdline, expected_options, actual_options)
		}
		if expected_args == nil {
			expected_args = []string{}
		}
		if !reflect.DeepEqual(expected_args, cmd.Args) {
			t.Fatalf("Argument values incorrect (expected != actual):\nCommand line: %s\n%#v != %#v", cmdline, expected_args, cmd.Args)
		}
		cmd.Root().ResetAfterParseArgs()
	}

	root := NewRootCommand()
	root.Add(OptionSpec{Name: "--from-parent -p", Type: "count", Depth: 1})
	child1 := root.AddSubCommand("", "child1")
	child1.Add(OptionSpec{Name: "--choices", Choices: "a b c"})
	child1.Add(OptionSpec{Name: "--simple-string -s"})
	child1.Add(OptionSpec{Name: "--set-me", Type: "bool-set"})
	child1.Add(OptionSpec{Name: "--int", Type: "int"})
	child1.Add(OptionSpec{Name: "--float", Type: "float"})

	rt(
		child1, "test --from-parent child1 -ps ss --choices b --from-parent one two",
		&options{SimpleString: "ss", Choices: "b", FromParent: 3},
		"one", "two",
	)
	rt(child1, "test child1", &options{Choices: "a"})
	rt(child1, "test child1 --set-me --simple-string=foo one", &options{Choices: "a", SimpleString: "foo", SetMe: true}, "one")
	rt(child1, "test child1 --set-me --simple-string= one", &options{Choices: "a", SetMe: true}, "one")
	rt(child1, "test child1 --int -3 --simple-string -s --float=3.3", &options{Choices: "a", SimpleString: "-s", Int: -3, Float: 3.3})

	_, err := child1.ParseArgs(strings.Split("test child1 --choices x", " "))
	if err == nil {
		t.Fatalf("Invalid choice not caught")
	}
	root.ResetAfterParseArgs()
}
