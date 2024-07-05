import os


def main(args: 'list[str]') -> None:
    # allow running this kitten via map key kitten choose-fonts
    os.execlp('kitten', 'kitten', *args)
