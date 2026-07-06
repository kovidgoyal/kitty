initialize_command: make debug
copy_resource: fonts

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

## Verification Pipeline

Before declaring a task complete, you must follow this exact verification lifecycle:
1. Run the local **Build Command** to guarantee zero compilation or compilation-stage type errors.
2. Run the local **Test Command** to run the full test suite
3. If errors occur, analyze the stdout logs completely before writing a fix. Do not guess.
4. If the change you have made is user facing, update the docs/changelog.rst
   file with a brief description of your changes
