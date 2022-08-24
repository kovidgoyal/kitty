package tui

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"
)

type Signal byte

const (
	SIGNULL Signal = 0
	SIGINT  Signal = 1
	SIGTERM Signal = 2
	SIGTSTP Signal = 3
	SIGHUP  Signal = 4
	SIGTTIN Signal = 5
	SIGTTOU Signal = 6
	SIGUSR1 Signal = 7
	SIGUSR2 Signal = 8
	SIGALRM Signal = 9
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
	default:
		return fmt.Sprintf("SIG#%s", *self)
	}
}

func as_signal(which os.Signal) Signal {
	switch which {
	case os.Interrupt:
		return SIGINT
	case syscall.SIGTERM:
		return SIGTERM
	case syscall.SIGTSTP:
		return SIGTSTP
	case syscall.SIGHUP:
		return SIGHUP
	case syscall.SIGTTIN:
		return SIGTTIN
	case syscall.SIGTTOU:
		return SIGTTOU
	case syscall.SIGUSR1:
		return SIGUSR1
	case syscall.SIGUSR2:
		return SIGUSR2
	case syscall.SIGALRM:
		return SIGALRM
	default:
		return SIGNULL
	}
}

const zero_go_signal = syscall.Signal(0)

func as_go_signal(which Signal) os.Signal {
	switch which {
	case SIGINT:
		return os.Interrupt
	case SIGTERM:
		return syscall.SIGTERM
	case SIGTSTP:
		return syscall.SIGTSTP
	case SIGHUP:
		return syscall.SIGHUP
	case SIGTTIN:
		return syscall.SIGTTIN
	case SIGTTOU:
		return syscall.SIGTTOU
	case SIGUSR1:
		return syscall.SIGUSR1
	case SIGUSR2:
		return syscall.SIGUSR2
	case SIGALRM:
		return syscall.SIGALRM
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
		case SIGTSTP:
			err := self.on_SIGTSTP()
			if err != nil {
				return err
			}
		}
	}
	return nil
}
