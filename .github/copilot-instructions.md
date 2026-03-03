# Repository Build & Test Instructions

## Build Procedures
- **Required dependencies**: A C compiler (either clang or gcc) and a Go compiler. The Go compiler
  should be at least the version mentioned in the go.mod file. On Linux, the
  X11 development libraries are also needed.
- **Bootstrap:** Always run `./dev.sh deps` to download all needed dependencies
- **Build command:** Run `./dev.sh build` to build the project
- Run `gen/config.py` to update generated config parsing code for both kitty
  and kitten. The `gen/go_code.py` generator is run automatically by the build
  command to keep generated Go code files up to date.
- To build individual kittens use the build command above **do not** try to run go build
  yourself.

## Test Procedures
- To run the complete test suite, run `./test.py`
- To run a specific test, run `./test.py test-name` t
  `test-name` is the name of the test without the
  leading `test_` for Python tests and without the leading `Test` for Go tests.

## Benchmarking
- To run the benchmark: `./benchmark.py`
