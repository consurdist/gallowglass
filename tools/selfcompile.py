#!/usr/bin/env python3
"""Run a Gallowglass source file through the Reaver-hosted self-host
compiler and diff the output against the Python bootstrap.

This is the fixed-point experiment: for any source S, we expect

  python_output(S) == reaver_hosted_compiler(S)

byte-for-byte.  If S is `compiler/src/Compiler.gls` itself, this is the
true compile-self property — the canonical self-hosting test.

Usage:

  python3 tools/selfcompile.py path/to/source.gls
  python3 tools/selfcompile.py path/to/source.gls --timeout 3600

Output:

  * Byte-identical → exit 0, prints a one-line "OK n bytes" summary.
  * Diverge → exit 1, prints the first-mismatch offset, the surrounding
    ±64 bytes from both sides, and the cumulative match length.
  * Reaver crash / non-zero exit → exit 2, prints stderr.
  * Timeout → exit 3.

Implementation notes:

  * The Python reference is produced by re-running the bootstrap
    pipeline (lex → parse → resolve → compile_program → emit_program)
    with module name 'Compiler' — matching what the Reaver-hosted
    compiler hardcodes.
  * The Reaver-hosted compiler is the standard `tools/run_reaver.py`
    pipeline, invoked with `--fn main_reaver --no-prelude` and the
    input piped on stdin.  Source bytes traverse bytesBar in/out of
    the PLAN evaluator.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REAVER_DIR = os.path.join(REPO_ROOT, 'vendor', 'reaver')
BOOT_PLAN = os.path.join(REAVER_DIR, 'src', 'plan', 'boot.plan')
COMPILER_GLS = os.path.join(REPO_ROOT, 'compiler', 'src', 'Compiler.gls')

sys.path.insert(0, REPO_ROOT)


def _python_reference(src: bytes) -> bytes:
    """Compile `src` via the Python bootstrap with module name 'Compiler'."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 50000))
    from bootstrap.lexer import lex
    from bootstrap.parser import parse
    from bootstrap.scope import resolve
    from bootstrap.codegen import compile_program
    from bootstrap.emit_pla import emit_program
    src_str = src.decode('utf-8')
    prog = parse(lex(src_str, '<input>'), '<input>')
    resolved, _ = resolve(prog, 'Compiler', {}, '<input>')
    compiled = compile_program(resolved, 'Compiler')
    return emit_program(compiled).encode('utf-8')


def _compile_compiler_plan() -> str:
    """Bootstrap-compile compiler/src/Compiler.gls to Plan Asm text."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 50000))
    from bootstrap.lexer import lex
    from bootstrap.parser import parse
    from bootstrap.scope import resolve
    from bootstrap.codegen import compile_program
    from bootstrap.emit_pla import emit_program
    with open(COMPILER_GLS) as f:
        compiler_src = f.read()
    prog = parse(lex(compiler_src, COMPILER_GLS), COMPILER_GLS)
    resolved, _ = resolve(prog, 'Compiler', {}, COMPILER_GLS)
    compiled = compile_program(resolved, 'Compiler')
    return emit_program(compiled)


def _reaver_run(plan_text: str, src: bytes, *, timeout: int, verbose: bool) -> tuple[bytes, bytes, int]:
    """Invoke Reaver's plan-assembler with `plan_text` as the loaded module
    and `src` piped on stdin.  Returns (stdout, stderr, returncode)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, 'compiler.plan'), 'w') as f:
            f.write(plan_text)
        shutil.copy(BOOT_PLAN, os.path.join(tmpdir, 'boot.plan'))
        if shutil.which('nix'):
            cmd = ['nix', 'develop', '--command', 'cabal', 'run', '-v0',
                   'plan-assembler', '--',
                   tmpdir, 'compiler', 'Compiler_main_reaver', '0']
        else:
            cmd = ['cabal', 'run', '-v0', 'plan-assembler', '--',
                   tmpdir, 'compiler', 'Compiler_main_reaver', '0']
        if verbose:
            print(f'-- reaver: {" ".join(cmd)}', file=sys.stderr)
        proc = subprocess.Popen(
            cmd, cwd=REAVER_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(input=src, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                import signal
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raise
        return stdout, stderr, proc.returncode


def _format_diff(reference: bytes, actual: bytes) -> str:
    """Return a human-readable diff snippet at the first divergent byte."""
    n = min(len(reference), len(actual))
    first_diff = n
    for i in range(n):
        if reference[i] != actual[i]:
            first_diff = i
            break
    out = [f'  first divergence at byte {first_diff} of {n}']
    ctx_lo = max(0, first_diff - 64)
    ctx_hi = min(max(len(reference), len(actual)), first_diff + 64)
    out.append(f'  reference[{ctx_lo}:{ctx_hi}] = {reference[ctx_lo:ctx_hi]!r}')
    out.append(f'  actual   [{ctx_lo}:{ctx_hi}] = {actual[ctx_lo:ctx_hi]!r}')
    out.append(f'  reference len = {len(reference)}, actual len = {len(actual)}')
    return '\n'.join(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Diff the Reaver-hosted self-host output against the Python bootstrap.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('source', help='Path to .gls source file (or `-` for stdin).')
    parser.add_argument('--timeout', type=int, default=600, metavar='SECS',
                        help='Reaver timeout in seconds (default: 600).')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--write-ref', metavar='PATH',
                        help='Write the Python reference output to PATH and exit.')
    parser.add_argument('--write-actual', metavar='PATH',
                        help='Write the Reaver-hosted output to PATH (in addition to diff).')
    args = parser.parse_args()

    if args.source == '-':
        src = sys.stdin.buffer.read()
    else:
        with open(args.source, 'rb') as f:
            src = f.read()

    if args.verbose:
        print(f'-- input: {len(src)} bytes', file=sys.stderr)

    t0 = time.monotonic()
    reference = _python_reference(src)
    t_ref = time.monotonic() - t0
    if args.verbose:
        print(f'-- python reference: {len(reference)} bytes in {t_ref:.2f}s',
              file=sys.stderr)

    if args.write_ref:
        with open(args.write_ref, 'wb') as f:
            f.write(reference)
        print(f'wrote {args.write_ref} ({len(reference)} bytes)')
        sys.exit(0)

    t0 = time.monotonic()
    plan_text = _compile_compiler_plan()
    t_compile = time.monotonic() - t0
    if args.verbose:
        print(f'-- compiled Compiler.gls in {t_compile:.2f}s '
              f'({len(plan_text)//1024} KB plan text)', file=sys.stderr)

    t0 = time.monotonic()
    try:
        actual, stderr, rc = _reaver_run(
            plan_text, src, timeout=args.timeout, verbose=args.verbose,
        )
    except subprocess.TimeoutExpired:
        print(f'TIMEOUT after {args.timeout}s', file=sys.stderr)
        sys.exit(3)
    t_reaver = time.monotonic() - t0
    if args.verbose:
        print(f'-- reaver-hosted output: {len(actual)} bytes in {t_reaver:.2f}s '
              f'(rc={rc})', file=sys.stderr)

    if args.write_actual:
        with open(args.write_actual, 'wb') as f:
            f.write(actual)
        print(f'wrote {args.write_actual} ({len(actual)} bytes)',
              file=sys.stderr)

    if rc != 0:
        print(f'REAVER FAILED (exit {rc})', file=sys.stderr)
        print(f'stderr-tail={stderr[-2000:]!r}', file=sys.stderr)
        sys.exit(2)

    if reference == actual:
        print(f'OK {len(reference)} bytes (python {t_ref:.2f}s, '
              f'reaver {t_reaver:.2f}s)')
        sys.exit(0)
    else:
        print('DIVERGE', file=sys.stderr)
        print(_format_diff(reference, actual), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
