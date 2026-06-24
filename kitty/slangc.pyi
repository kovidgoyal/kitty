class Error(Exception):
    pass


class GlobalSession:
    def __init__(self, enable_glsl_input: bool = False): ...
