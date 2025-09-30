package atexit

import (
	"bufio"
	"fmt"
	"os"
	"os/signal"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/utils/shm"
)

var _ = fmt.Print

func main() (rc int, err error) {
	signal.Ignore()
	done_channel := make(chan bool)
	lines := []string{}

	defer os.Stdout.Close()

	go func() {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			lines = append(lines, scanner.Text())
			fmt.Println(len(lines))
		}
		done_channel <- true
	}()

	<-done_channel
	rc = 0
	for _, line := range lines {
		if action, rest, found := strings.Cut(line, " "); found {
			switch action {
			case "unlink":
				if err := os.Remove(rest); err != nil && !os.IsNotExist(err) {
					fmt.Fprintln(os.Stderr, "Failed to unlink:", rest, "with error:", err)
					rc = 1
				}
			case "shm_unlink":
				if err := shm.ShmUnlink(rest); err != nil && !os.IsNotExist(err) {
					fmt.Fprintln(os.Stderr, "Failed to shm_unlink:", rest, "with error:", err)
					rc = 1
				}
			case "rmtree":
				if err := os.RemoveAll(rest); err != nil && !os.IsNotExist(err) {
					fmt.Fprintln(os.Stderr, "Failed to rmtree:", rest, "with error:", err)
					rc = 1
				}
			}
		}
	}
	return
}

func EntryPoint(root *cli.Command) {
	root.AddSubCommand(&cli.Command{
		Name:            "__atexit__",
		Hidden:          true,
		OnlyArgsAllowed: true,
		Run: func(cmd *cli.Command, args []string) (rc int, err error) {
			if len(args) != 0 {
				return 1, fmt.Errorf("Usage: __atexit__")
			}
			return main()
		},
	})
}
