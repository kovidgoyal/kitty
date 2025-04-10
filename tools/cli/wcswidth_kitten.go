package cli

import (
	"fmt"
)

var _ = fmt.Print

func main() (rc int, err error) {
	return
}

func WcswidthKittenEntryPoint(root *Command) {
	root.AddSubCommand(&Command{
		Name:            "__width_test__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *Command, args []string) (rc int, err error) {
			if len(args) != 0 {
				return 1, fmt.Errorf("Usage: __width_test__")
			}
			return main()
		},
	})
}
