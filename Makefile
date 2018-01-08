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
