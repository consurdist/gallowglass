#!/usr/bin/env python3
"""Run a Gallowglass source file under Reaver (plan-assembler).

Compiles <source.gls> via the Python bootstrap, emits Plan Assembler
text, and hands it to Reaver's plan-assembler CLI.

Modes
-----
Load-only  (no --fn)   Verify all bindings parse cleanly.  Good for
                       checking that a file compiles without errors.

I/O        (--fn NAME) Apply the entry function under Reaver with
                       stdin/stdout wired through.  Use this for
                       programs built on Reaver.RPLAN.input/output.

Trace      (--trace)   Inspect a pure PLAN value.  Embeds a
                       (Trace MODULE_NAME 0) call at the top level;
                       Reaver evaluates and prints the value.

Examples
--------
  # Verify all bindings load:
  python3 tools/run_reaver.py compiler/src/Compiler.gls Compiler

  # Run an I/O entry point (pipe source in, get Plan Asm out):
  echo 'let xx = 42' | \\
      python3 tools/run_reaver.py compiler/src/Compiler.gls Compiler --fn main_reaver

  # Inspect a pure value:
  python3 tools/run_reaver.py src/Foo.gls Foo --fn my_value --trace

  # Source that uses Core.Nat, Core.List, etc. (prelude loaded by default):
  python3 tools/run_reaver.py src/App.gls App --fn main --trace

  # Monolithic file with no use declarations (skip prelude for speed):
  python3 tools/run_reaver.py compiler/src/Compiler.gls Compiler --no-prelude

Prerequisites
-------------
  vendor/reaver/ must exist (run tools/vendor.sh if not).
  Either nix or cabal must be on PATH.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REAVER_DIR = os.path.join(REPO_ROOT, 'vendor', 'reaver')
BOOT_PLAN = os.path.join(REAVER_DIR, 'src', 'plan', 'boot.plan')

sys.path.insert(0, REPO_ROOT)


def _check_reaver() -> None:
    if not os.path.isdir(REAVER_DIR):
        sys.exit(
            f'error: {REAVER_DIR} not found\n'
            f'  run: tools/vendor.sh'
        )
    if not os.path.isfile(BOOT_PLAN):
        sys.exit(
            f'error: {BOOT_PLAN} not found\n'
            f'  run: tools/vendor.sh'
        )
    if shutil.which('nix') is None and shutil.which('cabal') is None:
        sys.exit(
            'error: neither nix nor cabal found on PATH\n'
            '  install one to use the Reaver backend'
        )


def _fq(module: str, fn: str) -> str:
    """Plan Asm binding name: Module.Name + fn → Module_Name_fn."""
    return module.replace('.', '_') + '_' + fn.replace('.', '_')


def _bindings(plan_text: str) -> list[str]:
    """Return all binding names in the Plan Asm text, in order."""
    return re.findall(r'\(#bind (\S+)', plan_text)


def _check_binding(plan_text: str, fq: str, module: str) -> None:
    """Exit with a helpful message if *fq* is not in the compiled output."""
    names = _bindings(plan_text)
    if fq in names:
        return
    prefix = module.replace('.', '_') + '_'
    user = [n[len(prefix):] for n in names if n.startswith(prefix)]
    msg = [f"error: '{fq}' not found in compiled output"]
    if user:
        msg.append(f"  available in {module!r}:")
        msg.extend(f"    --fn {n}" for n in user)
    else:
        msg.append(f"  no bindings found for module {module!r}")
        msg.append(f"  (is the module name correct? compiled {len(names)} total bindings)")
    sys.exit('\n'.join(msg))


def _compile(source_path: str, module: str, *, with_prelude: bool) -> str:
    """Compile source to Plan Assembler text."""
    from bootstrap.lexer import lex
    from bootstrap.parser import parse
    from bootstrap.scope import resolve
    from bootstrap.codegen import compile_program
    from bootstrap.emit_pla import emit_program

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 50000))

    with open(source_path) as f:
        src = f.read()

    if with_prelude:
        from bootstrap.build import build_with_prelude
        compiled = build_with_prelude(module, src)
        return emit_program(compiled)
    else:
        prog = parse(lex(src, source_path), source_path)
        resolved, _ = resolve(prog, module, {}, source_path)
        compiled = compile_program(resolved, module)
        return emit_program(compiled)


def _compile_trace(source_path: str, module: str, fn: str, *,
                   with_prelude: bool) -> str:
    """Compile source to Plan Assembler text with a (Trace FQ 0) trailer."""
    from bootstrap.lexer import lex
    from bootstrap.parser import parse
    from bootstrap.scope import resolve
    from bootstrap.codegen import compile_program
    from bootstrap.emit_pla import emit_program

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 50000))

    with open(source_path) as f:
        src = f.read()

    fq = _fq(module, fn)
    trailer = f'(Trace {fq} 0)\n'

    if with_prelude:
        from bootstrap.build import build_with_prelude
        compiled = build_with_prelude(module, src)
        return emit_program(compiled, trailer=trailer)
    else:
        prog = parse(lex(src, source_path), source_path)
        resolved, _ = resolve(prog, module, {}, source_path)
        compiled = compile_program(resolved, module)
        return emit_program(compiled, trailer=trailer)


def _reaver_cmd(tmpdir: str, stem: str, fn_fq: str | None = None,
                arg: str = '0') -> list[str]:
    """Build the plan-assembler invocation."""
    base = ['nix', 'develop', '--command', 'cabal', 'run', '-v0',
            'plan-assembler', '--'] if shutil.which('nix') else \
           ['cabal', 'run', '-v0', 'plan-assembler', '--']
    cmd = base + [tmpdir, stem]
    if fn_fq is not None:
        cmd += [fn_fq, arg]
    return cmd


def _run_load_only(plan_text: str, stem: str, module: str, *,
                   timeout: int, verbose: bool) -> int:
    """Verify all bindings parse; list user bindings; exit 0 on success."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, f'{stem}.plan'), 'w') as f:
            f.write(plan_text)
        shutil.copy(BOOT_PLAN, os.path.join(tmpdir, 'boot.plan'))
        cmd = _reaver_cmd(tmpdir, stem)
        if verbose:
            print(f'-- plan-assembler load: {" ".join(cmd)}', file=sys.stderr)
        result = subprocess.run(
            cmd, cwd=REAVER_DIR, capture_output=True, timeout=timeout,
        )
    combined = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    if result.returncode != 0:
        print(f'error: plan-assembler failed (exit {result.returncode})',
              file=sys.stderr)
        print(combined, file=sys.stderr)
        return result.returncode
    if verbose:
        print(combined, file=sys.stderr)
    prefix = module.replace('.', '_') + '_'
    user = [n[len(prefix):] for n in _bindings(plan_text) if n.startswith(prefix)]
    print(f'OK — all bindings loaded.  {module!r} exports:')
    for name in user:
        print(f'  {name}')
    return 0


def _run_trace(plan_text: str, stem: str, *, timeout: int, verbose: bool) -> int:
    """Run with embedded Trace trailer; print value to stdout."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, f'{stem}.plan'), 'w') as f:
            f.write(plan_text)
        shutil.copy(BOOT_PLAN, os.path.join(tmpdir, 'boot.plan'))
        cmd = _reaver_cmd(tmpdir, stem)
        if verbose:
            print(f'-- plan-assembler trace: {" ".join(cmd)}', file=sys.stderr)
        result = subprocess.run(
            cmd, cwd=REAVER_DIR, capture_output=True, timeout=timeout,
        )
    out = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    if result.returncode != 0:
        print(f'error: plan-assembler failed (exit {result.returncode})',
              file=sys.stderr)
    print(out, end='')
    return result.returncode


def _run_io(plan_text: str, stem: str, fn_fq: str, arg: str, *,
            timeout: int, verbose: bool) -> int:
    """Run with stdin/stdout wired through (RPLAN I/O programs)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, f'{stem}.plan'), 'w') as f:
            f.write(plan_text)
        shutil.copy(BOOT_PLAN, os.path.join(tmpdir, 'boot.plan'))
        cmd = _reaver_cmd(tmpdir, stem, fn_fq, arg)
        if verbose:
            print(f'-- plan-assembler run: {" ".join(cmd)}', file=sys.stderr)
        result = subprocess.run(
            cmd, cwd=REAVER_DIR, timeout=timeout,
        )
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Run a Gallowglass source file under Reaver.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('source', help='Path to .gls source file')
    parser.add_argument('module', help='Module name (e.g. Compiler, Core.Nat)')
    parser.add_argument('--fn', metavar='ENTRY',
                        help='Entry function (bare name; FQ = Module_ENTRY)')
    parser.add_argument('--arg', default='0', metavar='ARG',
                        help='strNat arg passed to entry function (default: 0)')
    parser.add_argument('--trace', action='store_true',
                        help='Inspect a pure value via (Trace ...) instead of '
                             'wiring stdin/stdout through')
    parser.add_argument('--no-prelude', action='store_true',
                        help='Skip Core prelude (for self-contained source)')
    parser.add_argument('--timeout', type=int, default=120, metavar='SECS',
                        help='Subprocess timeout in seconds (default: 120)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show compile time and Reaver command')
    args = parser.parse_args()

    if args.trace and args.fn is None:
        parser.error('--trace requires --fn')

    _check_reaver()

    # Compile
    t0 = time.monotonic()
    try:
        if args.trace:
            plan_text = _compile_trace(
                args.source, args.module, args.fn,
                with_prelude=not args.no_prelude,
            )
        else:
            plan_text = _compile(
                args.source, args.module,
                with_prelude=not args.no_prelude,
            )
    except Exception as e:
        sys.exit(f'compile error: {e}')

    elapsed = time.monotonic() - t0
    stem = args.module.replace('.', '_').lower()

    if args.verbose:
        n_bindings = plan_text.count('(#bind ')
        print(f'-- compiled {n_bindings} bindings in {elapsed:.2f}s '
              f'({len(plan_text)//1024}K Plan Asm)', file=sys.stderr)

    # Validate function exists before invoking Reaver
    if args.fn is not None:
        _check_binding(plan_text, _fq(args.module, args.fn), args.module)

    # Dispatch
    try:
        if args.fn is None:
            rc = _run_load_only(plan_text, stem, args.module,
                                timeout=args.timeout, verbose=args.verbose)
        elif args.trace:
            rc = _run_trace(plan_text, stem,
                            timeout=args.timeout, verbose=args.verbose)
        else:
            fq = _fq(args.module, args.fn)
            rc = _run_io(plan_text, stem, fq, args.arg,
                         timeout=args.timeout, verbose=args.verbose)
    except subprocess.TimeoutExpired:
        sys.exit(f'error: Reaver timed out after {args.timeout}s')

    sys.exit(rc)


if __name__ == '__main__':
    main()
