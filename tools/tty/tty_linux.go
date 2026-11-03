// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tty

import "golang.org/x/sys/unix"

func Tcgetattr(fd int, argp *unix.Termios) error {
	return unix.IoctlSetTermios(fd, unix.TCGETS, argp)
}

func Tcsetattr(fd int, action uintptr, argp *unix.Termios) error {
	var request uint
	switch action {
	case TCSANOW:
		request = unix.TCSETS
	case TCSADRAIN:
		request = unix.TCSETSW
	case TCSAFLUSH:
		request = unix.TCSETSF
	default:
		return unix.EINVAL
	}
	return unix.IoctlSetTermios(fd, request, argp)
}
