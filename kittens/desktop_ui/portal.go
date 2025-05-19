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
	"github.com/kovidgoyal/kitty/tools/utils"
)

var _ = fmt.Print

const PORTAL_APPEARANCE_NAMESPACE = "org.freedesktop.appearance"
const PORTAL_COLOR_SCHEME_KEY = "color-scheme"
const PORTAL_BUS_NAME = "org.freedesktop.impl.portal.desktop.kitty"
const SETTINGS_OBJECT_PATH = "/org/freedesktop/portal/desktop"
const SETTINGS_INTERFACE = "org.freedesktop.impl.portal.Settings"
const CHANGE_SETTINGS_OBJECT_PATH = "/net/kovidgoyal/kitty/portal"
const CHANGE_SETTINGS_INTERFACE = "net.kovidgoyal.kitty.settings"

// Special portal setting used to check if we are being called by xdg-desktop-portal
const SETTINGS_CANARY_NAMESPACE = "net.kovidgoyal.kitty"
const SETTINGS_CANARY_KEY = "status"

type ColorScheme uint32

const (
	NO_PREFERENCE ColorScheme = iota
	DARK
	LIGHT
)

type SettingsMap map[string]map[string]dbus.Variant

type Portal struct {
	bus      *dbus.Conn
	settings SettingsMap
	lock     sync.Mutex
}

func NewPortal(opts *Options) *Portal {
	ans := Portal{}
	ans.settings = SettingsMap{
		SETTINGS_CANARY_NAMESPACE: map[string]dbus.Variant{
			SETTINGS_CANARY_KEY: dbus.MakeVariant("running"),
		},
	}
	ans.settings[PORTAL_APPEARANCE_NAMESPACE] = map[string]dbus.Variant{}
	switch opts.Color_scheme {
	case "dark":
		ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(DARK))
	case "light":
		ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(LIGHT))
	default:
		ans.settings[PORTAL_APPEARANCE_NAMESPACE][PORTAL_COLOR_SCHEME_KEY] = dbus.MakeVariant(uint32(NO_PREFERENCE))
	}
	return &ans
}

type PropSpec map[string]*prop.Prop
type SignalSpec map[string][]struct {
	Name, Type string
}
type MethodSpec map[string][]struct {
	Name, Type string
	Out        bool
}

func ExportInterface(conn *dbus.Conn, object any, interface_name, object_path string, method_spec MethodSpec, prop_spec PropSpec, signal_spec SignalSpec) (err error) {
	op := dbus.ObjectPath(object_path)
	method_map := make(map[string]string, len(method_spec))
	methods := []introspect.Method{}
	if len(method_spec) > 0 {
		for method_name, args := range method_spec {
			method_map[method_name] = method_name
			meth_args := make([]introspect.Arg, len(args))
			for i, a := range args {
				meth_args[i] = introspect.Arg{
					Name:      a.Name,
					Type:      a.Type,
					Direction: utils.IfElse(a.Out, "out", "in"),
				}
			}
			methods = append(methods, introspect.Method{
				Name: method_name,
				Args: meth_args,
			})
		}
	}
	if err = conn.ExportWithMap(object, method_map, op, interface_name); err != nil {
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
		Methods:    methods,
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
	if err = conn.Export(introspect.NewIntrospectable(n), op, introspect.IntrospectData.Name); err != nil {
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
	props := PropSpec{
		"version": {Value: uint32(1), Writable: false, Emit: prop.EmitFalse},
	}
	signals := SignalSpec{
		"SettingChanged": {{"namespace", "s"}, {"key", "s"}, {"value", "v"}},
	}
	methods := MethodSpec{
		"Read":    {{"namespace", "s", false}, {"key", "s", false}, {"value", "v", true}},
		"ReadAll": {{"namespaces", "as", false}, {"value", "a{sa{sv}}", true}},
	}
	if err = ExportInterface(self.bus, self, SETTINGS_INTERFACE, SETTINGS_OBJECT_PATH, methods, props, signals); err != nil {
		return
	}
	methods = MethodSpec{
		"ChangeSetting": {{"namespace", "s", false}, {"key", "s", false}, {"value", "v", false}},
	}
	props["version"].Value = uint32(1)
	if err = ExportInterface(self.bus, self, CHANGE_SETTINGS_INTERFACE, CHANGE_SETTINGS_OBJECT_PATH, methods, props, nil); err != nil {
		return
	}
	return
}

func ParseValue(value, value_type_signature string) (dbus.Variant, error) {
	s, err := dbus.ParseSignature(value_type_signature)
	if err != nil {
		return dbus.Variant{}, fmt.Errorf("%s is not a valid type signature: %w", value_type_signature, err)
	}
	v, err := dbus.ParseVariant(value, s)
	if err != nil {
		return dbus.Variant{}, fmt.Errorf("%s is not a valid value for signature: %s with error: %w", value, value_type_signature, err)
	}
	return v, nil
}

func (self *Portal) ChangeSetting(namespace, key string, value dbus.Variant) *dbus.Error {
	self.lock.Lock()
	defer self.lock.Unlock()
	if self.settings[namespace] == nil {
		self.settings[namespace] = map[string]dbus.Variant{}
	}
	self.settings[namespace][key] = value

	if e := self.bus.Emit(
		SETTINGS_OBJECT_PATH,
		SETTINGS_INTERFACE+".SettingChanged",
		namespace,
		key,
		value,
	); e != nil {
		fmt.Fprintf(os.Stderr, "Couldn't emit signal: %s", e)
	}
	return nil
}

func (self *Portal) Read(namespace, key string) (dbus.Variant, *dbus.Error) {
	self.lock.Lock()
	defer self.lock.Unlock()
	if m, found := self.settings[namespace]; found {
		if v, found := m[key]; found {
			return v, nil
		}
	}
	return dbus.Variant{}, dbus.NewError("org.freedesktop.portal.Error.NotFound", []any{fmt.Sprintf("the setting %s in the namespace %s is not supported", key, namespace)})
}

func (self *Portal) ReadAll(namespaces []string) (map[string]map[string]dbus.Variant, *dbus.Error) {
	self.lock.Lock()
	defer self.lock.Unlock()
	var matched_namespaces = SettingsMap{}
	if len(namespaces) == 0 {
		matched_namespaces = self.settings
	} else {
		for _, namespace := range namespaces {
			if namespace == "" {
				matched_namespaces = self.settings
				break
			} else {
				if strings.HasSuffix(namespace, ".*") {
					namespace = namespace[:len(namespace)-1]
					for candidate := range self.settings {
						if strings.HasPrefix(candidate, namespace) {
							matched_namespaces[candidate] = map[string]dbus.Variant{}
						}
					}
				} else if _, found := self.settings[namespace]; found {
					matched_namespaces[namespace] = map[string]dbus.Variant{}
				}
			}
		}
	}
	values := map[string]map[string]dbus.Variant{}
	for namespace := range matched_namespaces {
		values[namespace] = make(map[string]dbus.Variant, len(self.settings[namespace]))
		maps.Copy(values[namespace], self.settings[namespace])
	}
	return values, nil
}
