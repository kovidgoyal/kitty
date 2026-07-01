#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Map the custom extensions to the required glslangValidator stage strings
stage_mapping = {
    '.vert.glsl': 'vert',
    '.frag.glsl': 'frag',
    '.vertex.glsl': 'vert',
    '.fragment.glsl': 'frag',
}


def validate_glsl_files(shader_files: Iterable[str | Path], verbose: bool = False) -> None:
    error_count = 0

    # Process each shader file
    for file_path in sorted(Path(f) for f in shader_files):
        # Identify extension matching suffix
        matched_ext = next(ext for ext in stage_mapping if file_path.name.endswith(ext))
        stage = stage_mapping[matched_ext]
        if verbose:
            print(f'Validating: {file_path.name}')
        result = subprocess.run(['glslangValidator', '-S', stage, str(file_path)],)

        # Check exit code
        if result.returncode != 0:
            error_count += 1
            print(f'❌ Failed: {file_path.name}', file=sys.stderr)
        else:
            if verbose:
                print(f'✅ Passed: {file_path.name}')

        if verbose:
            print('-' * 50)

    # Print execution summary
    if error_count == 0:
        if verbose:
            print("Success: All shaders validated successfully!")
    else:
        raise SystemExit(f"Failure: {error_count} shader(s) failed validation.")


def validate_glsl_dir(directory_path: str, verbose: bool = False) -> None:
    '''
    Validates all GLSL shaders in the specified directory with names matching
    name.vert.glsl or name.frag.glsl using glslangValidator.
    '''
    target_dir = Path(directory_path)

    if not target_dir.is_dir():
        raise SystemExit(f"Error: Directory '{directory_path}' does not exist.")

    # Find all files matching the patterns
    shader_files: list[Path] = []
    for ext in stage_mapping.keys():
        shader_files.extend(target_dir.glob(f'*{ext}'))

    if not shader_files:
        if verbose:
            print(f"No matching shaders (*.vert.glsl or *.frag.glsl) found in '{target_dir}'.")
        return
    validate_glsl_files(shader_files)


if __name__ == "__main__":
    dir_to_scan = sys.argv[1] if len(sys.argv) > 1 else 'shaders'
    validate_glsl_dir(dir_to_scan, verbose=True)
