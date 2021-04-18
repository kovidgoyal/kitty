" Scan the following dirs recursively for tags
let g:project_tags_dirs = ['kitty', 'kittens']
if exists('g:ale_linters')
    let g:ale_linters['python'] = ['mypy', 'flake8']
else
    let g:ale_linters = {'python': ['mypy', 'flake8']}
endif
let g:ale_python_mypy_executable = './mypy-editor-integration'
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
