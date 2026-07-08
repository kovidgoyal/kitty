initialize_command: make debug
copy_resource: fonts
copy_resource: bypy/b/linux/64/pkg/slang
add_to_path: bypy/b/linux/64/pkg/slang/bin
prepend_to_path: kitty/launcher

# System Instructions & Project Context

## Project Architecture & Stack
This is a multi-language repository. Adhere strictly to the idiomatic styling, patterns, and type safety of each respective language ecosystem present in the codebase. Do not mix patterns across language boundaries.

## Rules for Code Generation
- **Type Safety**: Enforce strict typing. Never use `any` or loose types.
- **Error Handling**: Implement explicit error handling. Avoid silent failures or empty catch blocks.
- **Dependency Minimization**: Use existing project utilities and native standard libraries before suggesting new external packages.
- **Local Context**: Search the codebase for existing patterns before writing boilerplate structure from scratch.

## Project Execution Workflows
You must always use the following custom scripts to build, verify, and test changes. Do not use generic toolchains such as `go test` or `pytest` or `./setup.py test`.

### 🛠️ Build Commands
Execute the following command to compile all modules and check for syntax or type errors. Do not try to build go code using `go build` or similar generic commands.
```bash
make debug
```

### Lint commands

Execute the following two commands to fix any formatting issues in your code:
```
ruff check --fix
gofmt -s -l -w tools kittens
```

### 🧪 Test Commands
Execute this command to run the test suite across all language domains:
```bash
./test.py
```

To isolate testing to a specific test use, use the test name without the leading
"test" prefix. For example, to run a python test named test_my_function, use
```bash
./test.py my_function
```

To run all tests in a specific file, for example, in kitty_tests/screen.py, use
```bash
./test.py --module screen
```

To run a Go test named TestMyFunction, use:
```bash
./test.py MyFunction
```

## Remote control API for verification

kitty has a comprehensive remote control API you can use for manual verification of
your changes. Run kitty as:

    kitty -o allow_remote_control=y --listen-on=@test-kitty-xxx

Then, you can take a screenshot of kitty and save it to test.png with:

    kitten @ --to=@test-kitty-xxx screenshot test.png

You can create window and tabs, send key events to kitty, query kitty
state, etc using the various remote control sub-commands, which you can query
using:

    kitten @ --help


## Verification Pipeline

Before declaring a task complete, you must follow this exact verification lifecycle:
1. Run the linting tools above to cleanup any formatting issues in your code
2. Run the local **Build Command** to guarantee zero compilation or compilation-stage type errors.
3. Run the local **Test Command** to run the full test suite
4. If errors occur, analyze the stdout logs completely before writing a fix. Do not guess.
5. If your changes involve rendering changes to kitty manually verify
   them by running kitty and using the remote control API as described above.
6. If the change you have made is user facing, update the docs/changelog.rst
   file with a brief description of your changes
