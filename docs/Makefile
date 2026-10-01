# Minimal makefile for Sphinx documentation
#

ifdef FAIL_WARN
override FAIL_WARN=-W
endif

# Ignore these variables if they come from the environment, users can have
# unrelated environment variables with these short names, for example, colors
# set by shell themes. They can still be set on the make command line.
ifeq ($(origin O),environment)
override O=
endif
ifeq ($(origin OPTS),environment)
override OPTS=
endif

# You can set these variables from the command line.
SPHINXOPTS    = -n -q -j auto -T $(FAIL_WARN) $(OPTS)
SPHINXBUILD   = sphinx-build
SPHINXAUTOBUILD = sphinx-autobuild
SPHINXPROJ    = kitty
SOURCEDIR     = .
BUILDDIR      = _build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)


develop-docs:
	$(SPHINXAUTOBUILD) --ignore "$(abspath $(SOURCEDIR))/generated/*" --watch ../kitty --watch ../kittens -b dirhtml "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)
