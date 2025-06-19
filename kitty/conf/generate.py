#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import inspect
import os
import re
import textwrap
from collections.abc import Callable, Iterator
from typing import Any, get_type_hints

from kitty.conf.types import Definition, MultiOption, Option, ParserFuncType, unset
from kitty.simple_cli_definitions import serialize_as_go_string
from kitty.types import _T


def chunks(lst: list[_T], n: int) -> Iterator[list[_T]]:
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def atoi(text: str) -> str:
    return f'{int(text):08d}' if text.isdigit() else text


def natural_keys(text: str) -> tuple[str, ...]:
    return tuple(atoi(c) for c in re.split(r'(\d+)', text))


def generate_class(defn: Definition, loc: str) -> tuple[str, str]:
    class_lines: list[str] = []
    tc_lines: list[str] = []
    a = class_lines.append
    t = tc_lines.append
    a('class Options:')
    t('class Parser:')
    choices = {}
    imports: set[tuple[str, str]] = set()
    tc_imports: set[tuple[str, str]] = set()
    ki_imports: 're.Pattern[str]' = re.compile(r'\b((?:kittens|kitty).+?)[,\]]')

    def option_type_as_str(x: Any) -> str:
        needs_import = False
        if type(x) is type:
            ans = x.__name__
            needs_import = True
        else:
            ans = repr(x)
            ans = ans.replace('NoneType', 'None')
        if needs_import and getattr(x, '__module__', None) and x.__module__ not in ('builtins', 'typing'):
            imports.add((x.__module__, x.__name__))
        return ans

    def option_type_data(option: Option | MultiOption) -> tuple[Callable[[Any], Any], str]:
        func = option.parser_func
        if func.__module__ == 'builtins':
            return func, func.__name__
        th = get_type_hints(func)
        rettype = th['return']
        typ = option_type_as_str(rettype)
        if isinstance(option, MultiOption):
            typ = typ[typ.index('[') + 1:-1]
            typ = typ.replace('tuple', 'dict', 1)
            kq = ki_imports.search(typ)
            if kq is not None:
                kqi = kq.group(1)
                kqim, kqii = kqi.rsplit('.', 1)
                imports.add((kqim, ''))
        return func, typ

    is_mutiple_vars = {}
    option_names = set()
    color_table = list(map(str, range(256)))
    choice_dedup: dict[str, str] = {}
    choice_parser_dedup: dict[str, str] = {}

    def parser_function_declaration(option_name: str) -> None:
        t('')
        t(f'    def {option_name}(self, val: str, ans: dict[str, typing.Any]) -> None:')

    for option in sorted(defn.iter_all_options(), key=lambda a: natural_keys(a.name)):
        option_names.add(option.name)
        parser_function_declaration(option.name)
        if isinstance(option, MultiOption):
            mval: dict[str, dict[str, Any]] = {'macos': {}, 'linux': {}, '': {}}
            func, typ = option_type_data(option)
            for val in option:
                if val.add_to_default:
                    gr = mval[val.only]
                    for k, v in func(val.defval_as_str):
                        gr[k] = v
            is_mutiple_vars[option.name] = typ, mval
            sig = inspect.signature(func)
            tc_imports.add((func.__module__, func.__name__))
            if len(sig.parameters) == 1:
                t(f'        for k, v in {func.__name__}(val):')
                t(f'            ans["{option.name}"][k] = v')
            else:
                t(f'        for k, v in {func.__name__}(val, ans["{option.name}"]):')
                t(f'            ans["{option.name}"][k] = v')
            continue

        if option.choices:
            typ = 'typing.Literal[{}]'.format(', '.join(repr(x) for x in option.choices))
            ename = f'choices_for_{option.name}'
            if typ in choice_dedup:
                typ = choice_dedup[typ]
            else:
                choice_dedup[typ] = ename
            choices[ename] = typ
            typ = ename
            func = str
        elif defn.has_color_table and option.is_color_table_color:
            func, typ = option_type_data(option)
            t(f'        ans[{option.name!r}] = {func.__name__}(val)')
            tc_imports.add((func.__module__, func.__name__))
            cnum = int(option.name[5:])
            color_table[cnum] = f'0x{func(option.defval_as_string).__int__():06x}'
            continue
        else:
            func, typ = option_type_data(option)
            try:
                params = dict(inspect.signature(func).parameters)
            except Exception:
                params = {}
            if 'dict_with_parse_results' in params:
                t(f'        {func.__name__}(val, ans)')
            else:
                t(f'        ans[{option.name!r}] = {func.__name__}(val)')
            if func.__module__ != 'builtins':
                tc_imports.add((func.__module__, func.__name__))

        defval_as_obj = func(option.defval_as_string)
        if isinstance(defval_as_obj, frozenset):
            defval = 'frozenset({' + ', '.join(repr(x) for x in sorted(defval_as_obj)) + '})'
        else:
            defval = repr(defval_as_obj)
        if option.macos_defval is not unset:
            md = repr(func(option.macos_defval))
            defval = f'{md} if is_macos else {defval}'
            imports.add(('kitty.constants', 'is_macos'))
        a(f'    {option.name}: {typ} = {defval}')
        if option.choices:
            ecname = f'choices_for_{option.name}'
            crepr = f'frozenset({option.choices!r})'
            if crepr in choice_parser_dedup:
                crepr = choice_parser_dedup[crepr]
            else:
                choice_parser_dedup[crepr] = ecname
            t('        val = val.lower()')
            t(f'        if val not in self.choices_for_{option.name}:')
            t(f'            raise ValueError(f"The value {{val}} is not a valid choice for {option.name}")')
            t(f'        ans["{option.name}"] = val')
            t('')
            t(f'    {ecname} = {crepr}')

    for option_name, (typ, mval) in is_mutiple_vars.items():
        a(f'    {option_name}: {typ} = ' '{}')

    for parser, aliases in defn.deprecations.items():
        for alias in aliases:
            parser_function_declaration(alias)
            tc_imports.add((parser.__module__, parser.__name__))
            t(f'        {parser.__name__}({alias!r}, val, ans)')

    action_parsers = {}

    def resolve_import(ftype: str) -> str:
        if '.' in ftype:
            fmod, ftype = ftype.rpartition('.')[::2]
        else:
            fmod = f'{loc}.options.utils'
        imports.add((fmod, ftype))
        return ftype

    for aname, action in defn.actions.items():
        option_names.add(aname)
        action_parsers[aname] = func = action.parser_func
        th = get_type_hints(func)
        rettype = th['return']
        typ = option_type_as_str(rettype)
        typ = typ[typ.index('[') + 1:-1]
        a(f'    {aname}: list[{typ}] = []')
        for imp in action.imports:
            resolve_import(imp)
        for fname, ftype in action.fields.items():
            ftype = resolve_import(ftype)
            fval = f'{ftype}()' if ftype == 'AliasMap' else '{}'
            a(f'    {fname}: {ftype} = {fval}')
        parser_function_declaration(aname)
        t(f'        for k in {func.__name__}(val):')
        t(f'            ans[{aname!r}].append(k)')
        tc_imports.add((func.__module__, func.__name__))

    if defn.has_color_table:
        imports.add(('array', 'array'))
        a('    color_table: "array[int]" = array("L", (')
        for grp in chunks(color_table, 8):
            a('        ' + ', '.join(grp) + ',')
        a('    ))')

    a('    config_paths: tuple[str, ...] = ()')
    a('    all_config_paths: tuple[str, ...] = ()')
    a('    config_overrides: tuple[str, ...] = ()')
    a('')
    a('    def __init__(self, options_dict: dict[str, typing.Any] | None = None) -> None:')
    if defn.has_color_table:
        a('        self.color_table = array(self.color_table.typecode, self.color_table)')
    a('        if options_dict is not None:')
    a('            null = object()')
    a('            for key in option_names:')
    a('                val = options_dict.get(key, null)')
    a('                if val is not null:')
    a('                    setattr(self, key, val)')

    a('')
    a('    @property')
    a('    def _fields(self) -> tuple[str, ...]:')
    a('        return option_names')

    a('')
    a('    def __iter__(self) -> typing.Iterator[str]:')
    a('        return iter(self._fields)')

    a('')
    a('    def __len__(self) -> int:')
    a('        return len(self._fields)')

    a('')
    a('    def _copy_of_val(self, name: str) -> typing.Any:')
    a('        ans = getattr(self, name)')
    a('        if isinstance(ans, dict):\n            ans = ans.copy()')
    a('        elif isinstance(ans, list):\n            ans = ans[:]')
    a('        return ans')

    a('')
    a('    def _asdict(self) -> dict[str, typing.Any]:')
    a('        return {k: self._copy_of_val(k) for k in self}')

    a('')
    a('    def _replace(self, **kw: typing.Any) -> "Options":')
    a('        ans = Options()')
    a('        for name in self:')
    a('            setattr(ans, name, self._copy_of_val(name))')
    a('        for name, val in kw.items():')
    a('            setattr(ans, name, val)')
    a('        return ans')

    a('')
    a('    def __getitem__(self, key: int | str) -> typing.Any:')
    a('        k = option_names[key] if isinstance(key, int) else key')
    a('        try:')
    a('            return getattr(self, k)')
    a('        except AttributeError:')
    a('            pass')
    a('        raise KeyError(f"No option named: {k}")')

    if defn.has_color_table:
        a('')
        a('    def __getattr__(self, key: str) -> typing.Any:')
        a('        if key.startswith("color"):')
        a('            q = key[5:]')
        a('            if q.isdigit():')
        a('                k = int(q)')
        a('                if 0 <= k <= 255:')
        a('                    x = self.color_table[k]')
        a('                    return Color((x >> 16) & 255, (x >> 8) & 255, x & 255)')
        a('        raise AttributeError(key)')
        a('')
        a('    def __setattr__(self, key: str, val: typing.Any) -> typing.Any:')
        a('        if key.startswith("color"):')
        a('            q = key[5:]')
        a('            if q.isdigit():')
        a('                k = int(q)')
        a('                if 0 <= k <= 255:')
        a('                    self.color_table[k] = int(val)')
        a('                    return')
        a('        object.__setattr__(self, key, val)')

    a('')
    a('')
    a('defaults = Options()')
    a('')
    for option_name, (typ, mval) in is_mutiple_vars.items():
        a(f'defaults.{option_name} = {mval[""]!r}')
        if mval['macos']:
            imports.add(('kitty.constants', 'is_macos'))
            a('if is_macos:')
            a(f'    defaults.{option_name}.update({mval["macos"]!r}')
        if mval['macos']:
            imports.add(('kitty.constants', 'is_macos'))
            a('if not is_macos:')
            a(f'    defaults.{option_name}.update({mval["linux"]!r}')

    a('')
    for aname, func in action_parsers.items():
        a(f'defaults.{aname} = [')
        only: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        for sc in defn.iter_all_maps(aname):
            if not sc.add_to_default:
                continue
            text = sc.parseable_text
            if sc.only:
                only.setdefault(sc.only, []).append((text, func))
            else:
                for val in func(text):
                    a(f'    # {sc.name}')
                    a(f'    {val!r},')
        a(']')
        a('')
        if only:
            imports.add(('kitty.constants', 'is_macos'))
            for cond, items in only.items():
                cond = 'is_macos' if cond == 'macos' else 'not is_macos'
                a(f'if {cond}:')
                for (text, parser_func) in items:
                    for val in parser_func(text):
                        a(f'    defaults.{aname}.append({val!r})')
                a('')

    t('')
    t('')
    t('def create_result_dict() -> dict[str, typing.Any]:')
    t('    return {')
    for oname in is_mutiple_vars:
        t(f'        {oname!r}: {{}},')
    for aname in defn.actions:
        t(f'        {aname!r}: [],')
    t('    }')

    t('')
    t('')
    t(f'actions: frozenset[str] = frozenset({tuple(defn.actions)!r})')
    t('')
    t('')
    t('def merge_result_dicts(defaults: dict[str, typing.Any], vals: dict[str, typing.Any]) -> dict[str, typing.Any]:')
    t('    ans = {}')
    t('    for k, v in defaults.items():')
    t('        if isinstance(v, dict):')
    t('            ans[k] = merge_dicts(v, vals.get(k, {}))')
    t('        elif k in actions:')
    t('            ans[k] = v + vals.get(k, [])')
    t('        else:')
    t('            ans[k] = vals.get(k, v)')
    t('    return ans')
    tc_imports.add(('kitty.conf.utils', 'merge_dicts'))

    t('')
    t('')
    t('parser = Parser()')
    t('')
    t('')
    t('def parse_conf_item(key: str, val: str, ans: dict[str, typing.Any]) -> bool:')
    t('    func = getattr(parser, key, None)')
    t('    if func is not None:')
    t('        func(val, ans)')
    t('        return True')
    t('    return False')

    preamble = ['# generated by gen-config.py DO NOT edit', '']
    a = preamble.append

    def output_imports(imports: set[tuple[str, str]], add_module_imports: bool = True) -> None:
        a('# isort: skip_file')
        a('import typing')
        a('import collections.abc  # noqa: F401, RUF100')
        seen_mods = {'typing'}
        mmap: dict[str, list[str]] = {}
        for mod, name in imports:
            mmap.setdefault(mod, []).append(name)
        for mod in sorted(mmap):
            names = list(filter(None, sorted(mmap[mod])))
            if names:
                lines = textwrap.wrap(', '.join(names), 100)
                if len(lines) == 1:
                    s = lines[0]
                else:
                    s = '\n    '.join(lines)
                    s = f'(\n    {s}\n)'
                a(f'from {mod} import {s}')
            else:
                s = ''
            if add_module_imports and mod not in seen_mods and mod != s:
                a(f'import {mod}')
                seen_mods.add(mod)

    output_imports(imports)
    a('')
    if choices:
        for name, cdefn in choices.items():
            a(f'{name} = {cdefn}')

    a('')
    a('option_names = (')
    for option_name in sorted(option_names, key=natural_keys):
        a(f'    {option_name!r},')
    a(')')
    class_def = '\n'.join(preamble + ['', ''] + class_lines)

    preamble = ['# generated by gen-config.py DO NOT edit', '']
    a = preamble.append
    output_imports(tc_imports, False)

    return class_def, '\n'.join(preamble + ['', ''] + tc_lines)


def generate_c_conversion(loc: str, ctypes: list[Option | MultiOption]) -> str:
    lines: list[str] = []
    basic_converters = {
        'int': 'PyLong_AsLong', 'uint': 'PyLong_AsUnsignedLong', 'bool': 'PyObject_IsTrue',
        'float': 'PyFloat_AsFloat', 'double': 'PyFloat_AsDouble', 'percent': 'percent',
        'time': 'parse_s_double_to_monotonic_t', 'time-ms': 'parse_ms_long_to_monotonic_t'
    }

    for opt in ctypes:
        lines.append('')
        lines.append(f'static void\nconvert_from_python_{opt.name}(PyObject *val, Options *opts) ''{')
        is_special = opt.ctype.startswith('!')
        if is_special:
            func = opt.ctype[1:]
            lines.append(f'    {func}(val, opts);')
        else:
            func = basic_converters.get(opt.ctype, opt.ctype)
            lines.append(f'    opts->{opt.name} = {func}(val);')
        lines.append('}')
        lines.append('')
        lines.append(f'static void\nconvert_from_opts_{opt.name}(PyObject *py_opts, Options *opts) ''{')
        lines.append(f'    PyObject *ret = PyObject_GetAttrString(py_opts, "{opt.name}");')
        lines.append('    if (ret == NULL) return;')
        lines.append(f'    convert_from_python_{opt.name}(ret, opts);')
        lines.append('    Py_DECREF(ret);')
        lines.append('}')

    lines.append('')
    lines.append('static bool\nconvert_opts_from_python_opts(PyObject *py_opts, Options *opts) ''{')
    for opt in ctypes:
        lines.append(f'    convert_from_opts_{opt.name}(py_opts, opts);')
        lines.append('    if (PyErr_Occurred()) return false;')
    lines.append('    return true;')
    lines.append('}')

    preamble = ['// generated by gen-config.py DO NOT edit', '// vim:fileencoding=utf-8', '#pragma once', '#include "to-c.h"']
    return '\n'.join(preamble + ['', ''] + lines)


def write_output(loc: str, defn: Definition, extra_after_type_defn: str = '') -> None:
    cls, tc = generate_class(defn, loc)
    ctypes = []
    has_secret = []
    for opt in defn.root_group.iter_all_non_groups():
        if isinstance(opt, (Option, MultiOption)) and opt.ctype:
            ctypes.append(opt)
        if getattr(opt, 'has_secret', False):
            has_secret.append(opt.name)
    with open(os.path.join(*loc.split('.'), 'options', 'types.py'), 'w') as f:
        f.write(f'{cls}\n')
        f.write(extra_after_type_defn)
        if has_secret:
            f.write('\n\nsecret_options = ' + repr(tuple(has_secret)))
    with open(os.path.join(*loc.split('.'), 'options', 'parse.py'), 'w') as f:
        f.write(f'{tc}\n')
    if ctypes:
        c = generate_c_conversion(loc, ctypes)
        with open(os.path.join(*loc.split('.'), 'options', 'to-c-generated.h'), 'w') as f:
            f.write(f'{c}\n')


def go_type_data(parser_func: ParserFuncType, ctype: str, is_multiple: bool = False) -> tuple[str, str]:
    if ctype or is_multiple:
        if ctype in ('string', ''):
            if is_multiple:
                return 'string', '[]string{val}, nil'
            return 'string', 'val, nil'
        if ctype.startswith('strdict_'):
            _, rsep, fsep = ctype.split('_', 2)
            return 'map[string]string', f'config.ParseStrDict(val, `{rsep}`, `{fsep}`)'
        return f'*{ctype}', f'Parse{ctype}(val)'
    p = parser_func.__name__
    if p == 'int':
        return 'int64', 'strconv.ParseInt(val, 10, 64)'
    if p == 'str':
        return 'string', 'val, nil'
    if p == 'float':
        return 'float64', 'strconv.ParseFloat(val, 10, 64)'
    if p == 'to_bool':
        return 'bool', 'config.StringToBool(val), nil'
    if p == 'to_color':
        return 'style.RGBA', 'style.ParseColor(val)'
    if p == 'to_color_or_none':
        return 'style.NullableColor', 'style.ParseColorOrNone(val)'
    if p == 'positive_int':
        return 'uint64', 'strconv.ParseUint(val, 10, 64)'
    if p == 'positive_float':
        return 'float64', 'config.PositiveFloat(val, 10, 64)'
    if p == 'unit_float':
        return 'float64', 'config.UnitFloat(val)'
    if p == 'python_string':
        return 'string', 'config.StringLiteral(val)'
    th = get_type_hints(parser_func)
    rettype = th['return']
    return {int: 'int64', str: 'string', float: 'float64'}[rettype], f'{p}(val)'


mod_map = {
		"shift":     "shift",
		"⇧":         "shift",
		"alt":       "alt",
		"option":    "alt",
		"opt":       "alt",
		"⌥":         "alt",
		"super":     "super",
		"command":   "super",
		"cmd":       "super",
		"⌘":         "super",
		"control":   "ctrl",
		"ctrl":      "ctrl",
		"⌃":         "ctrl",
		"hyper":     "hyper",
		"meta":      "meta",
		"num_lock":  "num_lock",
		"caps_lock": "caps_lock",
}

def normalize_shortcut(spec: str) -> str:
    if spec.endswith('+'):
        spec = spec[:-1] + 'plus'
    parts = spec.lower().split('+')
    key = parts[-1]
    if len(parts) == 1:
        return key
    mods = parts[:-1]
    return '+'.join(mod_map.get(x, x) for x in mods) + '+' + key


def normalize_shortcuts(spec: str) -> Iterator[str]:
    spec = spec.replace('++', '+plus')
    spec = re.sub(r'([^+])>', '\\1\0', spec)
    for x in spec.split('\0'):
        yield normalize_shortcut(x)


def gen_go_code(defn: Definition) -> str:
    lines = ['import "fmt"', 'import "strconv"', 'import "github.com/kovidgoyal/kitty/tools/config"',
             'import "github.com/kovidgoyal/kitty/tools/utils/style"',
             'var _ = fmt.Println', 'var _ = config.StringToBool', 'var _ = strconv.Atoi', 'var _ = style.ParseColor']
    a = lines.append
    keyboard_shortcuts = tuple(defn.iter_all_maps())
    choices = {}
    go_types = {}
    go_parsers = {}
    defaults = {}
    multiopts = {''}
    for option in sorted(defn.iter_all_options(), key=lambda a: natural_keys(a.name)):
        name = option.name.capitalize()
        if isinstance(option, MultiOption):
            go_types[name], go_parsers[name] = go_type_data(option.parser_func, option.ctype, True)
            multiopts.add(name)
            defval = []
            for x in option.items:
                if x.add_to_default:
                    defval.append(option.parser_func(x.defval_as_str))
            defaults[name] = defval
        else:
            defaults[name] = option.parser_func(option.defval_as_string)
            if option.choices:
                choices[name] = option.choices
                go_types[name] = f'{name}_Choice_Type'
                go_parsers[name] = f'Parse_{name}(val)'
                continue
            go_types[name], go_parsers[name] = go_type_data(option.parser_func, option.ctype)

    for oname in choices:
        a(f'type {go_types[oname]} int')
    a('type Config struct {')
    for name, gotype in go_types.items():
        if name in multiopts:
            a(f'{name} []{gotype}')
        else:
            a(f'{name} {gotype}')
    if keyboard_shortcuts:
        a('KeyboardShortcuts []*config.KeyAction')
    a('}')

    def cval(x: str) -> str:
        return x.replace('-', '_')

    a('func NewConfig() *Config {')
    a('return &Config{')
    from kitty.fast_data_types import Color

    def basic_defval(d: Any) -> str:
        if isinstance(d, str):
            dval = f'{name}_{cval(d)}' if name in choices else f'`{d}`'
        elif isinstance(d, bool):
            dval = repr(d).lower()
        elif isinstance(d, dict):
            dval = 'map[string]string{'
            for k, v in d.items():
                dval += f'"{serialize_as_go_string(k)}": "{serialize_as_go_string(v)}",'
            dval += '}'
        elif isinstance(d, list):
            dval = '[]string{'
            for k in d:
                dval += f'"{serialize_as_go_string(k)}",'
            dval += '}'
        elif isinstance(d, Color):
            dval = f'style.RGBA{{Red:{d.red}, Green: {d.green}, Blue: {d.blue}}}'
            if 'NullableColor' in go_types[name]:
                dval = f'style.NullableColor{{IsSet: true, Color:{dval}}}'
        else:
            dval = repr(d)
        return dval

    for name, pname in go_parsers.items():
        d = defaults[name]
        if d:
            a(f'{name}: {basic_defval(d)},')
    if keyboard_shortcuts:
        a('KeyboardShortcuts: []*config.KeyAction{')
        for sc in keyboard_shortcuts:
            aname, aargs = map(serialize_as_go_string, sc.action_def.partition(' ')[::2])
            a('{'f'Name: "{aname}", Args: "{aargs}", Normalized_keys: []string''{')
            ns = normalize_shortcuts(sc.key_text)
            a(', '.join(f'"{serialize_as_go_string(x)}"' for x in ns) + ',')
            a('}''},')
        a('},')

    a('}''}')

    for oname, choice_vals in choices.items():
        a('const (')
        for i, c in enumerate(choice_vals):
            c = cval(c)
            if i == 0:
                a(f'{oname}_{c} {oname}_Choice_Type = iota')
            else:
                a(f'{oname}_{c}')
        a(')')
        a(f'func (x {oname}_Choice_Type) String() string'' {')
        a('switch x {')
        a('default: return ""')
        for c in choice_vals:
            a(f'case {oname}_{cval(c)}: return "{c}"')
        a('}''}')
        a(f'func {go_parsers[oname].split("(")[0]}(val string) (ans {go_types[oname]}, err error) ''{')
        a('switch val {')
        for c in choice_vals:
            a(f'case "{c}": return {oname}_{cval(c)}, nil')
        vals = ', '.join(choice_vals)
        a(f'default: return ans, fmt.Errorf("%#v is not a valid value for %s. Valid values are: %s", val, "{c}", "{vals}")')
        a('}''}')

    has_parsers = bool(go_parsers or keyboard_shortcuts)
    a('func (c *Config) Parse(key, val string) (err error) {')
    if has_parsers:
        if go_parsers:
            a('switch key {')
            a('default: return fmt.Errorf("Unknown configuration key: %#v", key)')
            for oname, pname in go_parsers.items():
                ol = oname.lower()
                is_multiple = oname in multiopts
                a(f'case "{ol}":')
                if is_multiple:
                    a(f'var temp_val []{go_types[oname]}')
                else:
                    a(f'var temp_val {go_types[oname]}')
                a(f'temp_val, err = {pname}')
                a(f'if err != nil {{ return fmt.Errorf("Failed to parse {ol} = %#v with error: %w", val, err) }}')
                if is_multiple:
                    a(f'c.{oname} = append(c.{oname}, temp_val...)')
                else:
                    a(f'c.{oname} = temp_val')
        if keyboard_shortcuts:
            a('case "map":')
            a('tempsc, err := config.ParseMap(val)')
            a('if err != nil { return fmt.Errorf("Failed to parse map = %#v with error: %w", val, err) }')
            a('c.KeyboardShortcuts = append(c.KeyboardShortcuts, tempsc)')
        a('}')
        a('return}')
    else:
        a('return fmt.Errorf("Unknown configuration key: %#v", key)')
        a('}')
    return '\n'.join(lines)


def main() -> None:
    # To use run it as:
    # kitty +runpy 'from kitty.conf.generate import main; main()' /path/to/kitten/file.py
    import importlib
    import sys

    from kittens.runner import path_to_custom_kitten, resolved_kitten
    from kitty.constants import config_dir

    kitten = sys.argv[-1]
    if not kitten.endswith('.py'):
        kitten += '.py'
    kitten = resolved_kitten(kitten)
    path = os.path.realpath(path_to_custom_kitten(config_dir, kitten))
    if not os.path.dirname(path):
        raise SystemExit(f'No custom kitten named {kitten} found')
    sys.path.insert(0, os.path.dirname(path))
    package_name = os.path.basename(os.path.dirname(path))
    m = importlib.import_module('kitten_options_definition')
    defn = getattr(m, 'definition')
    loc = package_name
    cls, tc = generate_class(defn, loc)
    with open(os.path.join(os.path.dirname(path), 'kitten_options_types.py'), 'w') as f:
        f.write(f'{cls}\n')
    with open(os.path.join(os.path.dirname(path), 'kitten_options_parse.py'), 'w') as f:
        f.write(f'{tc}\n')
