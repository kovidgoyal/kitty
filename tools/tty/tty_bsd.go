//go:build darwin || freebsd || openbsd || netbsd || dragonfly
// +build darwin freebsd openbsd netbsd dragonfly

package tty

import (
	"golang.org/x/sys/unix"
)

func Tcgetattr(fd uintptr, argp *unix.Termios) error {
	return unix.IoctlSetTermios(int(fd), unix.TIOCGETA, argp)
}

func Tcsetattr(fd, opt uintptr, argp *unix.Termios) error {
	switch opt {
	case TCSANOW:
		opt = unix.TIOCSETA
	case TCSADRAIN:
		opt = unix.TIOCSETAW
	case TCSAFLUSH:
		opt = unix.TIOCSETAF
	default:
		return unix.EINVAL
	}
	return unix.IoctlSetTermios(int(fd), uint(opt), argp)
}
