ifdef V
		VVAL=--verbose
endif
ifdef VERBOSE
		VVAL=--verbose
endif

all:
	python3 setup.py $(VVAL)

test:
	python3 setup.py $(VVAL) test

clean:
	rm -f -r build
	rm -f compile_commands.json
	rm -f kitty/*.so kittens/unicode_input/*.so
	rm -f glfw/*-protocol.h glfw/*-protocol.c
	find -type d -name __pycache__ -exec rm -r '{}' +

# A debug build
debug:
	python3 setup.py build $(VVAL) --debug

# Build with the ASAN and UBSAN sanitizers
asan:
	python3 setup.py build $(VVAL) --debug --sanitize

profile:
	python3 setup.py build $(VVAL) --profile

logo/kitty.iconset/icon_256x256.png: logo/kitty.svg logo/make.py
	logo/make.py

rendered_logo: logo/kitty.iconset/icon_256x256.png

app: rendered_logo
	python3 setup.py kitty.app $(VVAL)
