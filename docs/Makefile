# Minimal makefile for Sphinx documentation
#

ifdef FAIL_WARN
override FAIL_WARN=-W
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
