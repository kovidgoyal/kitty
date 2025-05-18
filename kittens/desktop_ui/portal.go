package desktop_ui

import (
	"context"
	"fmt"
	"os"

	"github.com/kovidgoyal/dbus"
	"github.com/kovidgoyal/dbus/introspect"
	"github.com/kovidgoyal/dbus/prop"
)

var _ = fmt.Print

const PORTAL_COLOR_SCHEME_NAMESPACE = "org.freedesktop.appearance"
const PORTAL_COLOR_SCHEME_KEY = "color-scheme"
const PORTAL_BUS_NAME = "org.freedesktop.impl.portal.desktop.kitty"
const PORTAL_OBJ_PATH = "/org/freedesktop/portal/desktop"

const SETTINGS_INTERFACE = "org.freedesktop.impl.portal.Settings"

// Special portal setting used to check if darkman is in used by the portal.
const SETTINGS_CANARY_NAMESPACE = "net.kovidgoyal.kitty"
const SETTINGS_CANARY_KEY = "status"

type ColorScheme uint

const (
	NO_PREFERENCE ColorScheme = iota
	DARK
	LIGHT
)

type Portal struct {
	Color_scheme ColorScheme
	bus          *dbus.Conn
}

func NewPortal(opts *Options) *Portal {
	ans := Portal{}
	switch opts.Color_scheme {
	case "dark":
		ans.Color_scheme = DARK
	case "light":
		ans.Color_scheme = LIGHT
	default:
		ans.Color_scheme = NO_PREFERENCE
	}
	return &ans
}

func (self *Portal) Start(ctx context.Context) (err error) {
	if self.bus, err = dbus.SessionBus(); err != nil {
		return fmt.Errorf("could not connect to session D-Bus: %s", err)
	}

	// Define the "Version" prop (its value will be static).
	propsSpec := map[string]map[string]*prop.Prop{
		SETTINGS_INTERFACE: {
			"Version": {
				Value:    1,
				Writable: false,
				Emit:     prop.EmitTrue,
			},
		},
	}
	// Export the "Version" prop.
	versionProp, err := prop.Export(self.bus, PORTAL_OBJ_PATH, propsSpec)
	if err != nil {
		return fmt.Errorf("failed to export D-Bus prop: %v", err)
	}

	// Exoprt the D-Bus object.
	if err = self.bus.Export(self.bus, PORTAL_OBJ_PATH, SETTINGS_INTERFACE); err != nil {
		return fmt.Errorf("failed to export interface: %v", err)
	}

	// Declare change signal
	settingChanged := introspect.Signal{
		Name: "SettingChanged",
		Args: []introspect.Arg{
			{
				Name: "namespace",
				Type: "s",
			},
			{
				Name: "key",
				Type: "s",
			},
			{
				Name: "value",
				Type: "v",
			},
		},
	}

	readMethod := introspect.Method{
		Name: "Read",
		Args: []introspect.Arg{
			{
				Name:      "namespace",
				Type:      "s",
				Direction: "in",
			},
			{
				Name:      "key",
				Type:      "s",
				Direction: "in",
			},
			{
				Name:      "value",
				Type:      "v",
				Direction: "out",
			},
		},
	}
	readAllMethod := introspect.Method{
		Name: "ReadAll",
		Args: []introspect.Arg{
			{
				Name:      "namespaces",
				Type:      "as",
				Direction: "in",
			},
			{
				Name:      "value",
				Type:      "a{sa{sv}}",
				Direction: "out",
			},
		},
	}

	portalInterface := introspect.Interface{
		Name:       SETTINGS_INTERFACE,
		Signals:    []introspect.Signal{settingChanged},
		Properties: versionProp.Introspection(SETTINGS_INTERFACE),
		Methods:    []introspect.Method{readMethod, readAllMethod},
	}

	n := &introspect.Node{
		Name: PORTAL_OBJ_PATH,
		Interfaces: []introspect.Interface{
			introspect.IntrospectData,
			prop.IntrospectData,
			portalInterface,
		},
	}

	if err = self.bus.Export(
		introspect.NewIntrospectable(n),
		PORTAL_OBJ_PATH,
		"org.freedesktop.DBus.Introspectable",
	); err != nil {
		return fmt.Errorf("failed to export dbus name: %v", err)
	}

	reply, err := self.bus.RequestName(PORTAL_BUS_NAME, dbus.NameFlagDoNotQueue)
	if err != nil {
		return fmt.Errorf("failed to register dbus name: %v", err)
	}
	if reply != dbus.RequestNameReplyPrimaryOwner {
		return fmt.Errorf("can't register D-Bus name: name already taken")
	}

	return
}

func (self *Portal) ChangeMode(x string) (err error) {
	if self.bus == nil {
		return fmt.Errorf("cannot emit portal signal; no connection to dbus")
	}
	switch x {
	case "toggle":
		switch self.Color_scheme {
		case LIGHT:
			self.Color_scheme = DARK
		case DARK:
			self.Color_scheme = LIGHT
		}
	case "light":
		self.Color_scheme = LIGHT
	case "dark":
		self.Color_scheme = DARK
	case "no-preference":
		self.Color_scheme = NO_PREFERENCE
	default:
		return fmt.Errorf("%s is not a valid value for color-scheme. Valid values are: light, dark, no-preference and toggle", x)
	}

	if err = self.bus.Emit(
		PORTAL_OBJ_PATH,
		SETTINGS_INTERFACE+".SettingChanged",
		PORTAL_COLOR_SCHEME_NAMESPACE,
		PORTAL_COLOR_SCHEME_KEY,
		dbus.MakeVariant(self.Color_scheme),
	); err != nil {
		fmt.Fprintf(os.Stderr, "Couldn't emit signal: %s", err)
		err = nil
	}
	return
}

func (self *Portal) Read(namespace string, key string) (dbus.Variant, *dbus.Error) {
	if namespace == PORTAL_COLOR_SCHEME_NAMESPACE && key == PORTAL_COLOR_SCHEME_KEY {
		return dbus.MakeVariant(self.Color_scheme), nil
	}
	if namespace == SETTINGS_CANARY_NAMESPACE && key == SETTINGS_CANARY_KEY {
		return dbus.MakeVariant("running"), nil
	}
	return dbus.Variant{}, dbus.NewError("org.freedesktop.portal.Error.NotFound", []any{fmt.Sprintf("the setting %s in the namespace %s is not supported", key, namespace)})
}

func (self *Portal) ReadAll(namespaces []string) (map[string]map[string]dbus.Variant, *dbus.Error) {
	values := map[string]map[string]dbus.Variant{}
	for _, namespace := range namespaces {
		if namespace == PORTAL_COLOR_SCHEME_NAMESPACE {
			values[PORTAL_COLOR_SCHEME_NAMESPACE] = map[string]dbus.Variant{
				PORTAL_COLOR_SCHEME_KEY: dbus.MakeVariant(self.Color_scheme),
			}
		} else if namespace == SETTINGS_CANARY_NAMESPACE {
			values[SETTINGS_CANARY_NAMESPACE] = map[string]dbus.Variant{
				SETTINGS_CANARY_KEY: dbus.MakeVariant("running"),
			}
		}
	}
	return values, nil
}
