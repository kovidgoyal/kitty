" Scan the following dirs recursively for tags
let g:project_tags_dirs = ['kitty', 'kittens', 'tools']
set wildignore+==template.py
set wildignore+=tags
set expandtab
set tabstop=4
set shiftwidth=4
set softtabstop=0
set smarttab
python3 <<endpython
import sys
sys.path.insert(0, os.path.abspath('.'))
import kitty
endpython
