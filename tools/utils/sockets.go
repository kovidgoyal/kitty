// License: GPLv3 Copyright: 2022, Kovid Goyal, <kovid at kovidgoyal.net>

package utils

import (
	"fmt"
	"runtime"
	"strconv"
	"strings"

	"github.com/seancfoley/ipaddress-go/ipaddr"
)

func ParseSocketAddress(spec string) (network string, addr string, err error) {
	network, addr, found := strings.Cut(spec, ":")
	if !found {
		err = fmt.Errorf("Invalid socket address: %s must be prefix by a protocol such as unix:", spec)
		return
	}
	if network == "unix" {
		if strings.HasPrefix(addr, "@") && runtime.GOOS != "linux" {
			err = fmt.Errorf("Abstract UNIX sockets are only supported on Linux. Cannot use: %s", spec)
		}
		return
	}

	if network == "tcp" || network == "tcp6" || network == "tcp4" {
		host := ipaddr.NewHostName(addr)
		if host.IsAddress() {
			network = "ip"
		}
		return
	}
	if network == "ip" || network == "ip6" || network == "ip4" {
		host := ipaddr.NewHostName(addr)
		if !host.IsAddress() {
			err = fmt.Errorf("Not a valid IP address: %#v. Cannot use: %s", addr, spec)
		}
		return
	}
	if network == "fd" {
		fd := -1
		if fd, err = strconv.Atoi(addr); err != nil || fd < 0 {
			err = fmt.Errorf("Not a valid file descriptor number: %#v. Cannot use: %s", addr, spec)
		}
		return
	}
	err = fmt.Errorf("Unknown network type: %#v in socket address: %s", network, spec)
	return
}
