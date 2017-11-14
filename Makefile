all:
	python3 setup.py

test:
	python3 setup.py test

clean:
	python3 setup.py clean

# A debug build
debug:
	python3 setup.py build --debug

# Build with the ASAN and UBSAN sanitizers
asan:
	python3 setup.py build --debug --sanitize
