// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"time"

	"golang.org/x/sys/unix"
)

type Selector struct {
	read_set, write_set, err_set unix.FdSet
	read_fds, write_fds, err_fds map[int]bool
}

func CreateSelect(expected_number_of_fds int) *Selector {
	var ans Selector
	ans.read_fds = make(map[int]bool, expected_number_of_fds)
	ans.write_fds = make(map[int]bool, expected_number_of_fds)
	ans.err_fds = make(map[int]bool, expected_number_of_fds)
	return &ans
}

func (self *Selector) register(fd int, fdset *map[int]bool) {
	(*fdset)[fd] = true
}

func (self *Selector) RegisterRead(fd int) {
	self.register(fd, &self.read_fds)
}

func (self *Selector) RegisterWrite(fd int) {
	self.register(fd, &self.write_fds)
}

func (self *Selector) RegisterError(fd int) {
	self.register(fd, &self.err_fds)
}

func (self *Selector) unregister(fd int, fdset *map[int]bool) {
	(*fdset)[fd] = false
}

func (self *Selector) UnRegisterRead(fd int) {
	self.unregister(fd, &self.read_fds)
}

func (self *Selector) UnRegisterWrite(fd int) {
	self.unregister(fd, &self.write_fds)
}

func (self *Selector) UnRegisterError(fd int) {
	self.unregister(fd, &self.err_fds)
}

func (self *Selector) Wait(timeout time.Duration) (num_ready int, err error) {
	max_fd_num := 0

	init_set := func(s *unix.FdSet, m map[int]bool) {
		s.Zero()
		for fd, enabled := range m {
			if fd > -1 && enabled {
				if max_fd_num < fd {
					max_fd_num = fd
				}
				s.Set(fd)
			}
		}
	}
	init_set(&self.read_set, self.read_fds)
	init_set(&self.write_set, self.write_fds)
	init_set(&self.err_set, self.err_fds)
	num_ready, err = Select(max_fd_num+1, &self.read_set, &self.write_set, &self.err_set, timeout)
	if err == unix.EINTR {
		self.read_set.Zero()
		self.write_set.Zero()
		self.err_set.Zero()
		return 0, err
	}
	return
}

func (self *Selector) WaitForever() (num_ready int, err error) {
	return self.Wait(-1)
}

func (self *Selector) IsReadyToRead(fd int) bool {
	return fd > -1 && self.read_set.IsSet(fd)
}

func (self *Selector) IsReadyToWrite(fd int) bool {
	return fd > -1 && self.write_set.IsSet(fd)
}

func (self *Selector) IsErrored(fd int) bool {
	return fd > -1 && self.err_set.IsSet(fd)
}

func (self *Selector) UnregisterAll() {
	self.read_fds = make(map[int]bool)
	self.write_fds = make(map[int]bool)
	self.err_fds = make(map[int]bool)
}
