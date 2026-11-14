if __name__ == '__main__':
    import os
    import sys

    from datty.constants import daddy_exe

    os.execlp(daddy_exe(), 'daddy', *sys.argv)
