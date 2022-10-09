ifdef V
	VVAL=--verbose
endif
ifdef VERBOSE
	VVAL=--verbose
endif

ifdef FAIL_WARN
export FAIL_WARN
endif

THIS_MAKEFILE_DIR=$(dir $(realpath $(lastword $(MAKEFILE_LIST))))

all: setup.py
	python3 $< $(VVAL)

test: setup.py
	python3 $< $(VVAL) test

clean: setup.py
	python3 $< $(VVAL) clean

# A debug build
debug: setup.py
	python3 $< build $(VVAL) --debug

debug-event-loop: setup.py
	python3 $< build $(VVAL) --debug --extra-logging=event-loop

# Build with the ASAN and UBSAN sanitizers
asan: setup.py
	python3 $< build $(VVAL) --debug --sanitize

profile: setup.py
	python3 $< build $(VVAL) --profile

app: setup.py
	python3 $< kitty.app $(VVAL)

linux-package: setup.py FORCE
	rm -rf $(CURDIR)/linux-package
	python3 $< linux-package

FORCE:

man:
	$(MAKE) -C $(THIS_MAKEFILE_DIR)docs man BUILDDIR=$(CURDIR)/docs/_build

html:
	$(MAKE) -C $(THIS_MAKEFILE_DIR)docs html BUILDDIR=$(CURDIR)/docs/_build

dirhtml:
	$(MAKE) -C $(THIS_MAKEFILE_DIR)docs dirhtml BUILDDIR=$(CURDIR)/docs/_build

linkcheck:
	$(MAKE) -C $(THIS_MAKEFILE_DIR)docs linkcheck BUILDDIR=$(CURDIR)/docs/_build

website: publish.py
	$< --only website

docs: man html


develop-docs:
	$(MAKE) -C $(THIS_MAKEFILE_DIR)docs develop-docs BUILDDIR=$(CURDIR)/docs/_build
