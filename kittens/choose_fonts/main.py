import os

from kitty.constants import kitten_exe


def main(args: 'list[str]') -> None:
    # allow running this kitten via map key kitten choose-fonts
    os.execlp(kitten_exe(), 'kitten', *args)
