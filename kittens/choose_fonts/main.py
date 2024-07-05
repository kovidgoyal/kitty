if __name__ == '__main__':
    import os
    import sys

    from kitty.constants import kitten_exe
    os.execlp(kitten_exe(), 'kitten', *sys.argv)
