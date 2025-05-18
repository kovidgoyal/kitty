package desktop_ui

import (
	"fmt"
	"os"
	"strings"
	"sync"

	"github.com/kovidgoyal/dbus"
	"github.com/kovidgoyal/dbus/introspect"
	"github.com/kovidgoyal/dbus/prop"
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

const PORTAL_APPEARANCE_NAMESPACE = "org.freedesktop.appearance"
const PORTAL_COLOR_SCHEME_KEY = "color-scheme"
const PORTAL_BUS_NAME = "org.freedesktop.impl.portal.desktop.kitty"
const PORTAL_OBJ_PATH = "/org/freedesktop/portal/desktop"

const SETTINGS_INTERFACE = "org.freedesktop.impl.portal.Settings"

// Special portal setting used to check if darkman is in used by the portal.
const SETTINGS_CANARY_NAMESPACE = "net.kovidgoyal.kitty"
const SETTINGS_CANARY_KEY = "status"

type ColorScheme uint32

const (
	NO_PREFERENCE ColorScheme = iota
	DARK
	LIGHT
)

type Portal struct {
	Color_scheme ColorScheme
	lock         sync.Mutex
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

type PropSpec map[string]map[string]*prop.Prop

func ExportInterface(conn *dbus.Conn, object any, interface_name, object_path string, prop_spec PropSpec) (err error) {
	op := dbus.ObjectPath(object_path)
	if err = conn.Export(object, op, interface_name); err != nil {
		return fmt.Errorf("failed to export interface: %s at object path: %s with error: %w", interface_name, object_path, err)
	}
	var props *prop.Properties
	if prop_spec != nil {
		props, err = prop.Export(conn, op, prop_spec)
		if err != nil {
			return fmt.Errorf("failed to export properties with error: %w", err)
		}
	}
	n := &introspect.Node{
		Name: object_path,
		Interfaces: []introspect.Interface{
			introspect.IntrospectData,
			prop.IntrospectData,
			{
				Name:       interface_name,
				Methods:    introspect.Methods(object),
				Properties: props.Introspection(interface_name),
			},
		},
	}
	if err = conn.Export(introspect.NewIntrospectable(n), op, "org.freedesktop.DBus.Introspectable"); err != nil {
		return fmt.Errorf("failed to export introspected methods with error: %w", err)
	}
	return
}

func (self *Portal) Start() (err error) {
	if self.bus, err = dbus.SessionBus(); err != nil {
		return fmt.Errorf("could not connect to session D-Bus: %s", err)
	}
	reply, err := self.bus.RequestName(PORTAL_BUS_NAME, dbus.NameFlagDoNotQueue)
	if err != nil {
		return fmt.Errorf("failed to register dbus name: %v", err)
	}
	if reply != dbus.RequestNameReplyPrimaryOwner {
		return fmt.Errorf("can't register D-Bus name: name already taken")
	}
	props_spec := PropSpec{
		SETTINGS_INTERFACE: {
			"version": {Value: uint32(1), Writable: false, Emit: prop.EmitFalse},
		},
	}
	if err = ExportInterface(self.bus, self, SETTINGS_INTERFACE, PORTAL_OBJ_PATH, props_spec); err != nil {
		return
	}

	return
}

func (self *Portal) ChangeColorScheme(x string) (err error) {
	if self.bus == nil {
		return fmt.Errorf("cannot emit portal signal; no connection to dbus")
	}
	self.lock.Lock()
	defer self.lock.Unlock()
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
		PORTAL_APPEARANCE_NAMESPACE,
		PORTAL_COLOR_SCHEME_KEY,
		dbus.MakeVariant(self.Color_scheme),
	); err != nil {
		fmt.Fprintf(os.Stderr, "Couldn't emit signal: %s", err)
		err = nil
	}
	return
}

func (self *Portal) Read(namespace string, key string) (dbus.Variant, *dbus.Error) {
	self.lock.Lock()
	defer self.lock.Unlock()
	if namespace == PORTAL_APPEARANCE_NAMESPACE && key == PORTAL_COLOR_SCHEME_KEY {
		return dbus.MakeVariant(self.Color_scheme), nil
	}
	if namespace == SETTINGS_CANARY_NAMESPACE && key == SETTINGS_CANARY_KEY {
		return dbus.MakeVariant("running"), nil
	}
	return dbus.Variant{}, dbus.NewError("org.freedesktop.portal.Error.NotFound", []any{fmt.Sprintf("the setting %s in the namespace %s is not supported", key, namespace)})
}

func (self *Portal) ReadAll(namespaces []string) (map[string]map[string]dbus.Variant, *dbus.Error) {
	all_namespaces := utils.NewSetWithItems(PORTAL_APPEARANCE_NAMESPACE, SETTINGS_CANARY_NAMESPACE)
	matched_namespaces := utils.NewSet[string](all_namespaces.Len())
	if len(namespaces) == 0 {
		matched_namespaces = all_namespaces
	} else {
		for _, namespace := range namespaces {
			if namespace == "" {
				matched_namespaces = all_namespaces
				break
			} else {
				if strings.HasSuffix(namespace, ".*") {
					namespace = namespace[:len(namespace)-1]
					for candidate := range all_namespaces.Iterable() {
						if strings.HasPrefix(candidate, namespace) {
							matched_namespaces.Add(candidate)
						}
					}
				} else if all_namespaces.Has(namespace) {
					matched_namespaces.Add(namespace)
				}
			}
		}
	}
	self.lock.Lock()
	defer self.lock.Unlock()
	values := map[string]map[string]dbus.Variant{}
	for namespace := range matched_namespaces.Iterable() {
		if namespace == PORTAL_APPEARANCE_NAMESPACE {
			values[PORTAL_APPEARANCE_NAMESPACE] = map[string]dbus.Variant{
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
