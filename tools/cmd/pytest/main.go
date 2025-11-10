// License: GPLv3 Copyright: 2023, Kovid Goyal, <kovid at kovidgoyal.net>

package pytest

import (
	"fmt"
	"io"
	"os"

	"github.com/kovidgoyal/go-shm"
	"github.com/kovidgoyal/kitty/kittens/ssh"
	"github.com/kovidgoyal/kitty/tools/cli"
)

var _ = fmt.Print

func test_integration_with_python(args []string) (rc int, err error) {
	switch args[0] {
	default:
		return 1, fmt.Errorf("Unknown test type: %s", args[0])
	case "read":
		data, err := shm.ReadWithSizeAndUnlink(args[1])
		if err != nil {
			return 1, err
		}
		_, err = os.Stdout.Write(data)
		if err != nil {
			return 1, err
		}
	case "write":
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return 1, err
		}
		mmap, err := shm.CreateTemp("shmtest-", uint64(len(data)+shm.NUM_BYTES_FOR_SIZE))
		if err != nil {
			return 1, err
		}
		if err = shm.WriteWithSize(mmap, data, 0); err != nil {
			return 1, err
		}
		mmap.Close()
		fmt.Println(mmap.Name())
	}
	return 0, nil
}

func shm_entry_point(root *cli.Command) {
	root.AddSubCommand(&cli.Command{
		Name:            "shm",
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			return test_integration_with_python(args)
		},
	})

}
func EntryPoint(root *cli.Command) {
	root = root.AddSubCommand(&cli.Command{
		Name:   "__pytest__",
		Hidden: true,
	})
	shm_entry_point(root)
	ssh.TestEntryPoint(root)
}
