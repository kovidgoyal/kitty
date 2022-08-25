// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>
//go:build darwin || freebsd || openbsd || netbsd || dragonfly
// +build darwin freebsd openbsd netbsd dragonfly

package tty

import (
	"golang.org/x/sys/unix"
)

func Tcgetattr(fd int, argp *unix.Termios) error {
	return unix.IoctlSetTermios(fd, unix.TIOCGETA, argp)
}

func Tcsetattr(fd int, opt uintptr, argp *unix.Termios) error {
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
	return unix.IoctlSetTermios(fd, uint(opt), argp)
}
