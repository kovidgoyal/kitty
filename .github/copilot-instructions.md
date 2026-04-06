Before implementing any code changes or responding to a request, run the
following command:

python3 .github/workflows/ci.py build

This will download needed dependencies, then create all generated files
and build the project, making it ready for inspection.

# Repository Build & Test Instructions

## Build Procedures
- **Build command:** Run `./dev.sh build` to build the project
- Run `gen/config.py` to update generated config parsing code for both kitty
  and kitten. The `gen/go_code.py` generator is run automatically by the build
  command to keep generated Go code files up to date.
- To build individual kittens use the build command above **do not** try to run go build
  yourself.

Once a build is done, the kitty and kitten binaries will be in the `kitty/launcher` directory.
Note that the kitty binary can run python files using `kitty +launch file.py`.
When it does so the kitty fast_data_types module is available to the python
code.

## Test Procedures
- To run the complete test suite, run `./test.py`
- To run a specific test, run `./test.py test-name` t
  `test-name` is the name of the test without the
  leading `test_` for Python tests and without the leading `Test` for Go tests.
- Do not use go test or ./setup.py test to run tests

## PR guidance
When creating a pull request, add an entry in the file docs/changelog.rst
describing the change, if it is a user visible change. For internal changes, do
not add a changelog entry.
