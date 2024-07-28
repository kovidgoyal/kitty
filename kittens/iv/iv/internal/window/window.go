package window

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"golang.org/x/sys/unix"
)

type WindowParameters struct {
	Row    uint16
	Col    uint16
	XPixel uint16
	YPixel uint16
}

var GlobalWindowParameters WindowParameters

func InitWindowSizeHandler() {
	handleWindowSizeChange()

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGWINCH)

	go func() {
		for {
			sig := <-sigs
			if sig == syscall.SIGWINCH {
				handleWindowSizeChange()
			}
		}
	}()
}

func handleWindowSizeChange() {
	err := getWindowSize()
	if err != nil {
		fmt.Println("Error getting window size:", err)
	}
}

func getWindowSize() error {
	f, err := os.OpenFile("/dev/tty", unix.O_NOCTTY|unix.O_CLOEXEC|unix.O_NDELAY|unix.O_RDWR, 0666)
	if err != nil {
		return err
	}
	defer f.Close()

	sz, err := unix.IoctlGetWinsize(int(f.Fd()), unix.TIOCGWINSZ)
	if err != nil {
		return err
	}

	GlobalWindowParameters = WindowParameters{
		Row:    sz.Row,
		Col:    sz.Col,
		XPixel: sz.Xpixel,
		YPixel: sz.Ypixel,
	}

	fmt.Printf("rows: %v columns: %v width: %v height %v\n", sz.Row, sz.Col, sz.Xpixel, sz.Ypixel)
	return nil
}
