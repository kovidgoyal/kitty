" Scan the following dirs recursively for tags
let g:project_tags_dirs = ['kitty', 'pyte']
let g:syntastic_python_flake8_exec = 'flake8'
let g:ycm_python_binary_path = 'python3'
set wildignore+==template.py
set wildignore+=tags

python <<endpython
import sys
sys.path.insert(0, os.path.abspath('.'))
import kitty
endpython
