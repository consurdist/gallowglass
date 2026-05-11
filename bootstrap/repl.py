#!/usr/bin/env python3
"""
Gallowglass interactive REPL.

Input rules
-----------
* Lines starting with ``let``, ``type``, ``instance``, ``class``, or ``use``
  are declarations — input continues until a blank line is entered.
* Everything else is treated as an expression and submitted on the first Enter.
* A blank line always flushes whatever has been collected.
* Ctrl-D (EOF) exits cleanly.

Meta-commands (prefix ``:``)
----------------------------
    :reset    — discard all accumulated declarations (keep prelude)
    :quit     — exit
    :help     — print this message
"""

from __future__ import annotations

import readline  # noqa: F401  — side-effect: enables history + line editing
import sys

from bootstrap.jupyter_kernel import GallowglassEvaluator, CellResult

_BANNER = (
    'Gallowglass  (:help for commands, Ctrl-D to exit)\n'
    'Declarations (let/type/…) collect until a blank line; expressions submit on Enter.'
)

_HELP = """\
Gallowglass REPL

  :reset   discard accumulated declarations (prelude stays)
  :quit    exit  (also Ctrl-D)
  :help    this message

Input:
  Expressions submit on Enter:
    gg> add 1 2
    3

  Declarations collect until a blank line:
    gg> let double : Nat → Nat
    ..    = λ n → add n n
    ..
    double defined

  Multi-line expressions — wrap in a let, then evaluate the name:
    gg> let result =
    ..      match foo { | Bar → 1 | Baz → 2 }
    ..
    gg> result
"""

_DECL_PREFIXES = (
    'let ', 'let\t',
    'type ', 'type\t',
    'instance ', 'instance\t',
    'class ', 'class\t',
    'use ', 'use\t',
)


def _is_decl_start(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(p) for p in _DECL_PREFIXES)


def _read_cell() -> str | None:
    """Read one logical cell from stdin.

    Returns the source string, or None on EOF with no pending input.
    """
    lines: list[str] = []
    prompt = 'gg> '

    while True:
        try:
            line = input(prompt)
        except EOFError:
            print()
            return '\n'.join(lines) if lines else None

        # Leading blank lines before any input: ignore.
        if not line and not lines:
            continue

        # Blank line: submit whatever we have.
        if not line:
            break

        lines.append(line)

        # Single-line expression: submit immediately.
        if len(lines) == 1 and not _is_decl_start(line):
            break

        # Declaration (or already multi-line): keep collecting.
        prompt = '.. '

    return '\n'.join(lines)


def _format_error(err: dict) -> str:
    etype = err.get('etype', 'Error')
    val = err.get('evalue', '')
    tb = err.get('traceback', [])
    if tb:
        # Strip ANSI escapes from the traceback for plain terminal output.
        import re
        ansi = re.compile(r'\x1b\[[0-9;]*m')
        lines = [ansi.sub('', ln) for ln in tb]
        return '\n'.join(lines)
    return f'{etype}: {val}' if val else etype


def main() -> None:
    print(_BANNER)
    ev = GallowglassEvaluator()

    while True:
        src = _read_cell()
        if src is None:
            break

        src = src.strip()
        if not src:
            continue

        # Meta-commands.
        if src.startswith(':'):
            cmd = src.split()[0]
            if cmd in (':quit', ':q'):
                break
            elif cmd in (':reset', ':r'):
                ev.reset()
                print('(declarations cleared)')
            elif cmd in (':help', ':h', ':?'):
                print(_HELP)
            else:
                print(f"unknown command {cmd!r}  (:help for commands)")
            continue

        result: CellResult = ev.eval_cell(src)

        if result.error:
            print(_format_error(result.error), file=sys.stderr)
        elif result.value_text:
            print(result.value_text)
        # decls_only + no value_text → silent (e.g. blank cell)


if __name__ == '__main__':
    main()
