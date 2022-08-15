package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"kitty/tools/cli"
	"kitty/tools/cmd/at"
)

func main() {
	var root = cli.CreateCommand(&cobra.Command{
		Use:   "kitty-tool command [command options] [command args]",
		Short: "Fast, statically compiled implementations for various kitty command-line tools",
	})
	root.AddCommand(at.EntryPoint(root))

	cli.Init(root)
	if err := root.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
