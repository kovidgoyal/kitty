package desktop_ui

import (
	"fmt"
	"maps"
	"os"
	"strings"
	"sync"

	"github.com/kovidgoyal/dbus"
	"github.com/kovidgoyal/dbus/introspect"
	"github.com/kovidgoyal/dbus/prop"
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

type SettingsMap map[string]map[string]dbus.Variant

type Settings struct {
	items SettingsMap
	lock  sync.Mutex
}

type Portal struct {
	bus      *dbus.Conn
	settings Settings
}

func NewPortal(opts *Options) *Portal {
	ans := Portal{}
	ans.settings.items = SettingsMap{
		SETTINGS_CANARY_NAMESPACE: map[string]dbus.Variant{
			SETTINGS_CANARY_KEY: dbus.MakeVariant("running"),
		},
	}
	ans.settings.items[PORTAL_APPEARANCE_NAMESPACE] = map[string]dbus.Variant{}
	switch opts.Color_scheme {
	case "dark":
		ans.settings.items[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(DARK))
	case "light":
		ans.settings.items[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(LIGHT))
	default:
		ans.settings.items[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(NO_PREFERENCE))
	}
	return &ans
}

type PropSpec map[string]*prop.Prop
type SignalSpec map[string][]struct {
	Name, Type string
}

func ExportInterface(conn *dbus.Conn, object any, interface_name, object_path string, prop_spec PropSpec, signal_spec SignalSpec) (err error) {
	op := dbus.ObjectPath(object_path)
	if err = conn.Export(object, op, interface_name); err != nil {
		return fmt.Errorf("failed to export interface: %s at object path: %s with error: %w", interface_name, object_path, err)
	}
	var properties []introspect.Property
	p := prop.Map{interface_name: prop_spec}
	if len(prop_spec) > 0 {
		if props, err := prop.Export(conn, op, p); err != nil {
			return fmt.Errorf("failed to export properties with error: %w", err)
		} else {
			properties = props.Introspection(interface_name)
		}
	}
	var signals []introspect.Signal
	if len(signal_spec) > 0 {
		for signal_name, args := range signal_spec {
			sig_args := make([]introspect.Arg, len(args))
			for i, a := range args {
				sig_args[i] = introspect.Arg{
					Name:      a.Name,
					Type:      a.Type,
					Direction: "out",
				}
			}
			signals = append(signals, introspect.Signal{
				Name: signal_name,
				Args: sig_args,
			})
		}
	}
	interface_data := introspect.Interface{
		Name:       interface_name,
		Methods:    introspect.Methods(object),
		Properties: properties,
		Signals:    signals,
	}
	interfaces := []introspect.Interface{
		introspect.IntrospectData, interface_data,
	}
	if len(properties) > 0 {
		interfaces = append(interfaces, prop.IntrospectData)
	}
	n := &introspect.Node{Name: object_path, Interfaces: interfaces}
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
		"version": {Value: uint32(1), Writable: false, Emit: prop.EmitFalse},
	}
	signals := SignalSpec{
		"SettingChanged": {{"namespace", "s"}, {"key", "s"}, {"value", "v"}},
	}
	if err = ExportInterface(self.bus, &self.settings, SETTINGS_INTERFACE, PORTAL_OBJ_PATH, props_spec, signals); err != nil {
		return
	}

	return
}

func (self *Portal) ChangeSetting(namespace, key, value, value_type_signature string) (err error) {
	if self.bus == nil {
		return fmt.Errorf("cannot emit portal signal; no connection to dbus")
	}
	s, err := dbus.ParseSignature(value_type_signature)
	if err != nil {
		return fmt.Errorf("%s is not a valid type signature: %w", value_type_signature, err)
	}
	v, err := dbus.ParseVariant(value, s)
	if err != nil {
		return fmt.Errorf("%s is not a valid value for signature: %s with error: %w", value, value_type_signature, err)
	}
	self.settings.lock.Lock()
	defer self.settings.lock.Unlock()
	if self.settings.items[namespace] == nil {
		self.settings.items[namespace] = map[string]dbus.Variant{}
	}
	self.settings.items[namespace][key] = v

	if err = self.bus.Emit(
		PORTAL_OBJ_PATH,
		SETTINGS_INTERFACE+".SettingChanged",
		PORTAL_APPEARANCE_NAMESPACE,
		PORTAL_COLOR_SCHEME_KEY,
		v,
	); err != nil {
		fmt.Fprintf(os.Stderr, "Couldn't emit signal: %s", err)
		err = nil
	}
	return
}

func (self *Settings) Read(namespace string, key string) (dbus.Variant, *dbus.Error) {
	self.lock.Lock()
	defer self.lock.Unlock()
	if m, found := self.items[namespace]; found {
		if v, found := m[key]; found {
			return dbus.MakeVariant(v), nil
		}
	}
	return dbus.Variant{}, dbus.NewError("org.freedesktop.portal.Error.NotFound", []any{fmt.Sprintf("the setting %s in the namespace %s is not supported", key, namespace)})
}

func (self *Settings) ReadAll(namespaces []string) (map[string]map[string]dbus.Variant, *dbus.Error) {
	self.lock.Lock()
	defer self.lock.Unlock()
	var matched_namespaces = SettingsMap{}
	if len(namespaces) == 0 {
		matched_namespaces = self.items
	} else {
		for _, namespace := range namespaces {
			if namespace == "" {
				matched_namespaces = self.items
				break
			} else {
				if strings.HasSuffix(namespace, ".*") {
					namespace = namespace[:len(namespace)-1]
					for candidate := range self.items {
						if strings.HasPrefix(candidate, namespace) {
							matched_namespaces[candidate] = map[string]dbus.Variant{}
						}
					}
				} else if _, found := self.items[namespace]; found {
					matched_namespaces[namespace] = map[string]dbus.Variant{}
				}
			}
		}
	}
	values := map[string]map[string]dbus.Variant{}
	for namespace := range matched_namespaces {
		values[namespace] = make(map[string]dbus.Variant, len(self.items[namespace]))
		maps.Copy(values[namespace], self.items[namespace])
	}
	return values, nil
}
