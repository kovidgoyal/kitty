package utils

import "golang.org/x/sys/unix"

const (
	TCSETS  = 0x5402
	TCSETSW = 0x5403
	TCSETSF = 0x5404
	TCFLSH  = 0x540B
	TCSBRK  = 0x5409
	TCSBRKP = 0x5425

	IXON    = 0x00000400
	IXANY   = 0x00000800
	IXOFF   = 0x00001000
	CRTSCTS = 0x80000000
)

func Tcgetattr(fd int, argp *unix.Termios) error {
	return unix.IoctlSetTermios(fd, unix.TCGETS, argp)
}

func Tcsetattr(fd int, action uintptr, argp *unix.Termios) error {
	var request uintptr
	switch action {
	case TCSANOW:
		request = TCSETS
	case TCSADRAIN:
		request = TCSETSW
	case TCSAFLUSH:
		request = TCSETSF
	default:
		return unix.EINVAL
	}
	return unix.IoctlSetTermios(int(fd), uint(request), argp)
}
