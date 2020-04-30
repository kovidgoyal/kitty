" Scan the following dirs recursively for tags
let g:project_tags_dirs = ['kitty', 'kittens']
let g:syntastic_python_checkers = ['mypy', 'flake8']
let g:syntastic_python_mypy_exec = './mypy-editor-integration'
let g:ycm_python_binary_path = 'python3'
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
