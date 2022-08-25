// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package tui

import (
	"fmt"
	"golang.org/x/sys/unix"
	"os"
	"os/signal"
)

type Signal byte

const (
	SIGNULL  Signal = 0
	SIGINT   Signal = 1
	SIGTERM  Signal = 2
	SIGTSTP  Signal = 3
	SIGHUP   Signal = 4
	SIGTTIN  Signal = 5
	SIGTTOU  Signal = 6
	SIGUSR1  Signal = 7
	SIGUSR2  Signal = 8
	SIGALRM  Signal = 9
	SIGWINCH Signal = 10
)

func (self *Signal) String() string {
	switch *self {
	case SIGNULL:
		return "SIGNULL"
	case SIGINT:
		return "SIGINT"
	case SIGTERM:
		return "SIGTERM"
	case SIGTSTP:
		return "SIGTSTP"
	case SIGHUP:
		return "SIGHUP"
	case SIGTTIN:
		return "SIGTTIN"
	case SIGTTOU:
		return "SIGTTOU"
	case SIGUSR1:
		return "SIGUSR1"
	case SIGUSR2:
		return "SIGUSR2"
	case SIGALRM:
		return "SIGALRM"
	case SIGWINCH:
		return "SIGWINCH"
	default:
		return fmt.Sprintf("SIG#%d", *self)
	}
}

func as_signal(which os.Signal) Signal {
	switch which {
	case os.Interrupt:
		return SIGINT
	case unix.SIGTERM:
		return SIGTERM
	case unix.SIGTSTP:
		return SIGTSTP
	case unix.SIGHUP:
		return SIGHUP
	case unix.SIGTTIN:
		return SIGTTIN
	case unix.SIGTTOU:
		return SIGTTOU
	case unix.SIGUSR1:
		return SIGUSR1
	case unix.SIGUSR2:
		return SIGUSR2
	case unix.SIGALRM:
		return SIGALRM
	case unix.SIGWINCH:
		return SIGWINCH
	default:
		return SIGNULL
	}
}

const zero_go_signal = unix.Signal(0)

func as_go_signal(which Signal) os.Signal {
	switch which {
	case SIGINT:
		return os.Interrupt
	case SIGTERM:
		return unix.SIGTERM
	case SIGTSTP:
		return unix.SIGTSTP
	case SIGHUP:
		return unix.SIGHUP
	case SIGTTIN:
		return unix.SIGTTIN
	case SIGTTOU:
		return unix.SIGTTOU
	case SIGUSR1:
		return unix.SIGUSR1
	case SIGUSR2:
		return unix.SIGUSR2
	case SIGALRM:
		return unix.SIGALRM
	case SIGWINCH:
		return unix.SIGWINCH
	default:
		return zero_go_signal
	}
}

func write_signal(dest *os.File, which os.Signal) error {
	b := make([]byte, 1)
	b[0] = byte(as_signal(which))
	if b[0] == 0 {
		return nil
	}
	_, err := dest.Write(b)
	return err
}

func notify_signals(c chan os.Signal, signals ...Signal) func() {
	s := make([]os.Signal, len(signals))
	for i, x := range signals {
		g := as_go_signal(x)
		if g != zero_go_signal {
			s[i] = g
		}
	}
	signal.Notify(c, s...)
	return func() { signal.Reset(s...) }
}

func (self *Loop) read_signals(f *os.File, buf []byte) error {
	n, err := f.Read(buf)
	if err != nil {
		return err
	}
	buf = buf[:n]
	for _, s := range buf {
		switch Signal(s) {
		case SIGINT:
			err := self.on_SIGINT()
			if err != nil {
				return err
			}
		case SIGTERM:
			err := self.on_SIGTERM()
			if err != nil {
				return err
			}
		case SIGHUP:
			err := self.on_SIGHUP()
			if err != nil {
				return err
			}
		case SIGWINCH:
			err := self.on_SIGWINCH()
			if err != nil {
				return err
			}
		case SIGTSTP:
			err := self.on_SIGTSTP()
			if err != nil {
				return err
			}
		}
	}
	return nil
}
