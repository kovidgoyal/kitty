#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from collections import defaultdict

base = os.path.dirname(os.path.abspath(__file__))
os.chdir(base)


defns = defaultdict(list)

for line in open('kitty/kitty.conf'):
    if line.startswith('map '):
        _, sc, name = line.split(maxsplit=3)
        defns[name].append('`' + sc + '`')

defns = [':sc_{}: pass:quotes[{}]'.format(name, ' or '.join(defns[name])) for name in sorted(defns)]
defns = '\n'.join(defns)

raw = open('README.asciidoc').read()
pat = re.compile(r'^// START_SHORTCUT_BLOCK$.+?^// END_SHORTCUT_BLOCK$', re.M | re.DOTALL)
nraw = pat.sub('// START_SHORTCUT_BLOCK\n' +
               defns + '\n// END_SHORTCUT_BLOCK', raw)
if raw != nraw:
    print('Updating shortcuts block')
    open('README.asciidoc', 'w').write(nraw)
