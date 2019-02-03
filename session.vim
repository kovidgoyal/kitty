" Scan the following dirs recursively for tags
let g:project_tags_dirs = ['kitty']
let g:syntastic_python_flake8_exec = 'flake8'
let g:ycm_python_binary_path = 'python3'
set wildignore+==template.py
set wildignore+=tags
set expandtab
set tabstop=4
set shiftwidth=4
set softtabstop=0 
set smarttab
python <<endpython
import sys
sys.path.insert(0, os.path.abspath('.'))
import kitty
endpython
