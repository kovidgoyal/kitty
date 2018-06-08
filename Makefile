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
	python3 setup.py $(VVAL) clean

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

man:
	$(MAKE) FAIL_WARN=$(FAIL_WARN) -C docs man

html:
	$(MAKE) FAIL_WARN=$(FAIL_WARN) -C docs html
