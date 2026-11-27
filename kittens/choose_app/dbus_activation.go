// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package choose_app

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/kovidgoyal/dbus"
)

var _ = fmt.Print

// Starting applications via D-Bus, see
// https://specifications.freedesktop.org/desktop-entry-spec/latest/dbus.html

const dbus_application_interface = "org.freedesktop.Application"

// How long to wait for an application to be started via D-Bus
const dbus_activation_timeout = 15 * time.Second

// is_valid_bus_name returns true if name is a valid D-Bus well-known bus name
func is_valid_bus_name(name string) bool {
	if len(name) > 255 || !strings.Contains(name, ".") {
		return false
	}
	for elem := range strings.SplitSeq(name, ".") {
		if elem == "" || (elem[0] >= '0' && elem[0] <= '9') {
			return false
		}
		for _, c := range []byte(elem) {
			if !(c == '_' || c == '-' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) {
				return false
			}
		}
	}
	return true
}

// dbus_name returns the D-Bus bus name of the application, which is its
// desktop file id without the .desktop suffix
func (d *DesktopEntry) dbus_name() (string, bool) {
	name := d.IDWithoutSuffix()
	return name, is_valid_bus_name(name)
}

// dbus_object_path returns the object path at which the application exports
// the org.freedesktop.Application interface
func dbus_object_path(bus_name string) dbus.ObjectPath {
	return dbus.ObjectPath("/" + strings.ReplaceAll(strings.ReplaceAll(bus_name, ".", "/"), "-", "_"))
}

// platform_data returns the platform data for the org.freedesktop.Application
// methods, containing the activation token, if any
func platform_data(activation_token string) map[string]dbus.Variant {
	ans := map[string]dbus.Variant{}
	if activation_token != "" {
		ans["activation-token"] = dbus.MakeVariant(activation_token)
	}
	// The startup notification id used on X11, GLib sets this to the
	// activation token on Wayland as well
	if id := os.Getenv("DESKTOP_STARTUP_ID"); id != "" {
		ans["desktop-startup-id"] = dbus.MakeVariant(id)
	} else if activation_token != "" {
		ans["desktop-startup-id"] = dbus.MakeVariant(activation_token)
	}
	return ans
}

// activate_func starts an application via D-Bus, opening the URIs, if any
type activate_func func(bus_name string, uris []string, activation_token string) error

// dbus_activate starts the application with the specified bus name via the
// session bus, which starts the application if it is not running
func dbus_activate(bus_name string, uris []string, activation_token string) error {
	conn, err := dbus.ConnectSessionBus()
	if err != nil {
		return fmt.Errorf("could not connect to the session bus: %w", err)
	}
	defer conn.Close()
	ctx, cancel := context.WithTimeout(context.Background(), dbus_activation_timeout)
	defer cancel()
	obj := conn.Object(bus_name, dbus_object_path(bus_name))
	pd := platform_data(activation_token)
	var call *dbus.Call
	if len(uris) > 0 {
		call = obj.CallWithContext(ctx, dbus_application_interface+".Open", 0, uris, pd)
	} else {
		call = obj.CallWithContext(ctx, dbus_application_interface+".Activate", 0, pd)
	}
	if call.Err != nil {
		return fmt.Errorf("failed to start %s via D-Bus: %w", bus_name, call.Err)
	}
	return nil
}
