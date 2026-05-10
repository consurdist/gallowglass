#!/usr/bin/env python3
"""
Build script for tutorials/05-interval-arithmetic.ipynb. See
tutorials/_build_lesson_02.py for the pattern.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import nbformat
from nbformat import v4

from bootstrap.jupyter_kernel import GallowglassEvaluator


CELLS: list[tuple[str, str]] = [
    ('md', '''# Interval Arithmetic

In his *Mathematica* notebook, Jerry Keiper distinguishes two ways a \
computer can track numerical uncertainty:

- **Range arithmetic**: intervals are implicit — each floating-point value \
  carries a precision count bounding the rounding error, but the bounds are \
  not visible in the value itself.
- **Interval arithmetic**: intervals are explicit — a value is a pair \
  `[lo, hi]` that *guarantees* the true result lies between the endpoints. \
  Arithmetic propagates these bounds conservatively.

Gallowglass computes over natural numbers, so we build explicit interval \
arithmetic over `Nat`. A sensor reading known to lie between 10 and 15 is \
`MkInterval 10 15`; adding a second reading in `[3, 6]` gives a guaranteed \
sum in `[13, 21]`.

This notebook builds an interval typeclass from scratch:

1. **Type** — define `Interval`
2. **Functions** — `iv_lo`, `iv_hi`, `iv_width`, `iv_contains`, `iv_add`, `iv_mul`
3. **Show instance** — human-readable `"[lo, hi]"` rendering
4. **Typeclass** — `IvArith` abstracts over anything that behaves like an interval
5. **Instance** — wire `Interval` into `IvArith`
6. **Constrained wrappers** — dispatch through the typeclass constraint
7. **Applications** — tracking bounds through multi-step computations

Assumes `02-typeclasses.ipynb` — constrained wrappers, instance syntax.'''),

    ('md', '## Imports\n\n'
           'Arithmetic primitives from `Core.Nat`; text utilities from `Core.Text`:'),
    ('code', 'use Core.Nat unqualified { add, mul, sub, nat_lte }\n'
             'use Core.Text { Show, show, show_nat, text_concat }'),

    ('md', '## The `Interval` type\n\n'
           'An interval is a lower bound and an upper bound. One constructor, \n'
           'two `Nat` fields:'),
    ('code', 'type Interval =\n'
             '  | MkInterval Nat Nat'),

    ('md', 'Extract the bounds with pattern matching:'),
    ('code', 'let iv_lo : Interval → Nat\n'
             '  = λ ii → match ii { | MkInterval ll _ → ll }'),
    ('code', 'let iv_hi : Interval → Nat\n'
             '  = λ ii → match ii { | MkInterval _ hh → hh }'),

    ('md', '## Width and containment\n\n'
           'The **width** of an interval is `hi − lo`. `sub` is saturating '
           '(result is 0 when the subtrahend exceeds the minuend), so a '
           'degenerate point interval `MkInterval 5 5` safely yields width 0:'),
    ('code', 'let iv_width : Interval → Nat\n'
             '  = λ ii → match ii { | MkInterval ll hh → sub hh ll }'),
    ('code', 'iv_width (MkInterval 3 7)'),
    ('code', 'iv_width (MkInterval 5 5)'),

    ('md', '`iv_contains` tests whether `n ∈ [lo, hi]`. '
           '`nat_lte m n` returns `True` when `m ≤ n`; '
           '`if/then/else` dispatches on the `Bool` result:'),
    ('code', 'let iv_contains : Interval → Nat → Bool\n'
             '  = λ ii nn → match ii {\n'
             '      | MkInterval ll hh →\n'
             '          if nat_lte ll nn then nat_lte nn hh else False\n'
             '    }'),
    ('code', 'iv_contains (MkInterval 3 7) 5'),
    ('code', 'iv_contains (MkInterval 3 7) 10'),

    ('md', '## Interval arithmetic — standalone functions\n\n'
           'If `a ∈ [la, ha]` and `b ∈ [lb, hb]`, then `a + b ∈ [la+lb, ha+hb]`. '
           'The result is the *tightest* interval guaranteed to contain every '
           'possible sum:'),
    ('code', 'let iv_add : Interval → Interval → Interval\n'
             '  = λ aa bb → match aa {\n'
             '      | MkInterval la ha → match bb {\n'
             '          | MkInterval lb hb → MkInterval (add la lb) (add ha hb)\n'
             '        }\n'
             '    }'),

    ('md', 'For non-negative intervals, multiplication is monotone in both '
           'arguments — `[la·lb, ha·hb]` covers every possible product:'),
    ('code', 'let iv_mul : Interval → Interval → Interval\n'
             '  = λ aa bb → match aa {\n'
             '      | MkInterval la ha → match bb {\n'
             '          | MkInterval lb hb → MkInterval (mul la lb) (mul ha hb)\n'
             '        }\n'
             '    }'),

    ('md', 'Two intervals from Keiper\'s notebook — a ∈ [2, 3], b ∈ [4, 5]:'),
    ('code', 'iv_add (MkInterval 2 3) (MkInterval 4 5)'),
    ('code', 'iv_mul (MkInterval 2 3) (MkInterval 4 5)'),

    ('md', 'The width of the sum equals the sum of the widths — '
           'uncertainty accumulates linearly under addition:'),
    ('code', 'iv_width (iv_add (MkInterval 2 3) (MkInterval 4 5))'),

    ('md', '## `Show` instance\n\n'
           'Give `Interval` a human-readable `"[lo, hi]"` rendering. '
           '`show_nat` converts a `Nat` to decimal text; '
           '`text_concat` joins `Text` values:'),
    ('code', 'instance Show Interval {\n'
             '  show = λ ii → match ii {\n'
             '      | MkInterval ll hh →\n'
             '          text_concat "["\n'
             '            (text_concat (show_nat ll)\n'
             '              (text_concat ", "\n'
             '                (text_concat (show_nat hh) "]")))\n'
             '    }\n'
             '}'),

    ('md', 'The dispatch wrapper — same pattern as lesson 02; `show` only '
           'fires through a `let` whose type carries the `Show` constraint:'),
    ('code', 'let as_text : ∀ a. Show a => a → Text = λ xx → show xx'),
    ('code', 'as_text (MkInterval 3 7)'),

    ('md', '## The `IvArith` typeclass\n\n'
           'Abstract over the concrete type. Any type that implements `IvArith` '
           'exposes lower and upper bounds, supports addition and multiplication, '
           'tests containment, and reports its width.\n\n'
           'The class method names mirror the standalone function names — '
           'the same pattern as `class Add a { add }` in `Core.Nat` '
           'alongside `let add : Nat → Nat → Nat`:'),
    ('code', 'class IvArith i {\n'
             '  iv_lo       : i → Nat\n'
             '  iv_hi       : i → Nat\n'
             '  iv_add      : i → i → i\n'
             '  iv_mul      : i → i → i\n'
             '  iv_contains : i → Nat → Bool\n'
             '  iv_width    : i → Nat\n'
             '}'),

    ('md', '## Instance for `Interval`\n\n'
           'Wire the standalone functions into the instance. The pattern '
           '`iv_add = iv_add` assigns the standalone function to the class '
           'method — identical to `instance Add Nat { add = add }` in '
           '`Core.Nat`:'),
    ('code', 'instance IvArith Interval {\n'
             '  iv_lo       = iv_lo\n'
             '  iv_hi       = iv_hi\n'
             '  iv_add      = iv_add\n'
             '  iv_mul      = iv_mul\n'
             '  iv_contains = iv_contains\n'
             '  iv_width    = iv_width\n'
             '}'),

    ('md', '## Constrained wrappers\n\n'
           'Dispatch fires through a `let` whose type carries the constraint. '
           'Define thin wrappers — these are the entry points callers use:'),
    ('code', 'let add_iv : ∀ i. IvArith i => i → i → i\n'
             '  = λ aa bb → iv_add aa bb'),
    ('code', 'let mul_iv : ∀ i. IvArith i => i → i → i\n'
             '  = λ aa bb → iv_mul aa bb'),
    ('code', 'let contains_iv : ∀ i. IvArith i => i → Nat → Bool\n'
             '  = λ ii nn → iv_contains ii nn'),
    ('code', 'let width_iv : ∀ i. IvArith i => i → Nat\n'
             '  = λ ii → iv_width ii'),

    ('md', '## Application: propagating measurement bounds\n\n'
           'A pressure sensor reads between 10 and 15 PSI; a temperature '
           'sensor reads between 3 and 6. Track the guaranteed range of their '
           'sum:'),
    ('code', 'let pressure : Interval = MkInterval 10 15\n'
             'let temp     : Interval = MkInterval 3 6'),
    ('code', 'as_text (add_iv pressure temp)'),

    ('md', 'Is 20 guaranteed to be in the combined range? Is 22?'),
    ('code', 'contains_iv (add_iv pressure temp) 20'),
    ('code', 'contains_iv (add_iv pressure temp) 22'),

    ('md', 'And the product:'),
    ('code', 'as_text (mul_iv pressure temp)'),

    ('md', '## Application: polynomial over an interval\n\n'
           'Keiper\'s notebook evaluates Rump\'s pathological polynomial to '
           'demonstrate catastrophic cancellation in floating-point arithmetic. '
           'The Gallowglass analogue: evaluate `f(x) = 2·x² + 3·x` for '
           '`x ∈ [4, 6]` using interval arithmetic to bound the result.\n\n'
           'A constant wrapped as a point interval:'),
    ('code', 'let point : Nat → Interval = λ nn → MkInterval nn nn'),

    ('md', '`x` squared via `mul_iv`:'),
    ('code', 'let xx : Interval = MkInterval 4 6'),
    ('code', 'let x_sq : Interval = mul_iv xx xx'),
    ('code', 'as_text x_sq'),

    ('md', '`2·x²` and `3·x`:'),
    ('code', 'let term1 : Interval = mul_iv (point 2) x_sq'),
    ('code', 'let term2 : Interval = mul_iv (point 3) xx'),
    ('code', 'as_text term1'),
    ('code', 'as_text term2'),

    ('md', 'The guaranteed range of `f(x)`:'),
    ('code', 'let fx : Interval = add_iv term1 term2'),
    ('code', 'as_text fx'),

    ('md', 'Verify: at x=4, f(4) = 2·16 + 12 = 44. At x=6, f(6) = 2·36 + 18 = 90. '
           'Both should be contained in the computed interval:'),
    ('code', 'contains_iv fx 44'),
    ('code', 'contains_iv fx 90'),

    ('md', '## Width growth and accumulated uncertainty\n\n'
           'Each arithmetic step can widen the interval. Starting from a '
           'step size known only to lie in [1, 2], after three additions:'),
    ('code', 'let step : Interval = MkInterval 1 2'),
    ('code', 'let after3 : Interval = add_iv step (add_iv step step)'),
    ('code', 'as_text after3'),
    ('code', 'width_iv after3'),

    ('md', 'Width 3 — each step contributed its full uncertainty of 1. '
           'An exact step size of 1 gives total 3; step size of 2 gives 6. '
           'Both lie inside `[3, 6]`. The interval is a *guarantee*, not a '
           'best guess.\n\n'
           'Multiplication widens faster — `[1, 3]` squared:'),
    ('code', 'let base_iv : Interval = MkInterval 1 3'),
    ('code', 'as_text (mul_iv base_iv base_iv)'),
    ('code', 'width_iv (mul_iv base_iv base_iv)'),

    ('md', '## Fixed-point display\n\n'
           'The `Show` instance above renders raw `Nat` values. If your '
           'intervals represent measurements with two decimal places — `110` '
           'meaning `1.10`, `90` meaning `0.90` — you want the display to '
           'reflect that.\n\n'
           'The key idea: a single `scale` constant at the top of the notebook '
           'parameterises the renderer. Change `scale` from `100` to `1000` '
           'and you get three decimal places everywhere, with no other edits.'),

    ('code', 'use Core.Nat unqualified { nat_lt, div_nat, mod_nat }'),

    ('md', '`scale` is the notebook-level fixed-point denominator. '
           '`100` gives two decimal places:'),
    ('code', 'let scale : Nat = 100'),

    ('md', 'Three helper functions feed `show_fixed`.\n\n'
           '`count_digits n` — number of decimal digits in `n` '
           '(0 counts as 1):'),
    ('code', 'let count_digits : Nat → Nat\n'
             '  = λ nn →\n'
             '      if nat_lt nn 10\n'
             '      then 1\n'
             '      else add 1 (count_digits (div_nat nn 10))'),

    ('md', '`frac_digits sc` — decimal places implied by scale `sc`. '
           'For `sc = 100`: `count_digits 100 = 3`, minus 1 = 2 places:'),
    ('code', 'let frac_digits : Nat → Nat\n'
             '  = λ sc → sub (count_digits sc) 1'),

    ('md', '`zeros n` — a `Text` of `n` zero characters, used to '
           'left-pad the fractional part:'),
    ('code', 'let zeros : Nat → Text\n'
             '  = λ nn → match nn {\n'
             '      | 0  → ""\n'
             '      | kk → text_concat "0" (zeros kk)\n'
             '    }'),

    ('md', '`show_fixed sc nn` renders `nn` as a decimal with the number '
           'of places implied by `sc`. The padding count is '
           '`frac_digits sc − count_digits frac`, saturating to 0:'),
    ('code', 'let show_fixed : Nat → Nat → Text\n'
             '  = λ sc nn →\n'
             '      let whole = div_nat nn sc in\n'
             '      let frac  = mod_nat nn sc in\n'
             '      let pad   = sub (frac_digits sc) (count_digits frac) in\n'
             '      text_concat (show_nat whole)\n'
             '        (text_concat "."\n'
             '          (text_concat (zeros pad) (show_nat frac)))'),

    ('md', 'With `scale = 100`, `90` renders as `"0.90"` and `110` as `"1.10"`:'),
    ('code', 'show_fixed scale 90'),
    ('code', 'show_fixed scale 110'),
    ('code', 'show_fixed scale 5'),

    ('md', 'Partially apply `show_fixed` to pin the scale — the result is '
           'an ordinary `Nat → Text` function:'),
    ('code', 'let show_fp : Nat → Text = show_fixed scale'),
    ('code', 'show_fp 90'),
    ('code', 'show_fp 110'),

    ('md', '## `[lo, hi]` and `mid ± rad` in fixed-point\n\n'
           'Both display formats are parameterised by scale the same way:'),
    ('code', 'let show_iv_bounds : Nat → Interval → Text\n'
             '  = λ sc ii → match ii {\n'
             '      | MkInterval ll hh →\n'
             '          text_concat "["\n'
             '            (text_concat (show_fixed sc ll)\n'
             '              (text_concat ", "\n'
             '                (text_concat (show_fixed sc hh) "]")))\n'
             '    }'),
    ('code', 'let bounds_fp : Interval → Text = show_iv_bounds scale'),
    ('code', 'bounds_fp (MkInterval 90 110)'),

    ('code', 'let show_iv_pm : Nat → Interval → Text\n'
             '  = λ sc ii → match ii {\n'
             '      | MkInterval ll hh →\n'
             '          let mid = div_nat (add ll hh) 2 in\n'
             '          let rad = div_nat (sub hh ll) 2 in\n'
             '          text_concat (show_fixed sc mid)\n'
             '            (text_concat " +- " (show_fixed sc rad))\n'
             '    }'),
    ('code', 'let pm_fp : Interval → Text = show_iv_pm scale'),
    ('code', 'pm_fp (MkInterval 90 110)'),
    ('code', 'pm_fp (MkInterval 95 115)'),

    ('md', '## Application: resistances in a circuit\n\n'
           'Two resistors with manufacturing tolerance, measured in hundredths '
           'of an ohm. R₁ ∈ [1.30, 1.47] Ω, R₂ ∈ [2.20, 2.35] Ω — '
           'represented at scale 100 as:'),
    ('code', 'let r1 : Interval = MkInterval 130 147\n'
             'let r2 : Interval = MkInterval 220 235'),

    ('md', 'Series resistance R₁ + R₂, displayed both ways:'),
    ('code', 'bounds_fp (add_iv r1 r2)'),
    ('code', 'pm_fp (add_iv r1 r2)'),

    ('md', 'The `mid ± rad` form uses integer division, so results with odd '
           'total width round down. `[3.50, 3.82]` has width 32 (even), '
           'midpoint exactly 3.66, radius exactly 0.16 — no rounding here. '
           'An odd-width interval like `[3.50, 3.83]` would give '
           '`3.66 ± 0.16` (true midpoint 3.665, truncated).'),

    ('md', '## What\'s next\n\n'
           'You\'ve built a typeclass from scratch — type, functions, Show '
           'instance, class declaration, instance binding, constrained '
           'wrappers, fixed-point display, and applications.\n\n'
           '- **Change `scale`** — swap `100` for `1000` at the top and '
           're-run; `show_fp`, `bounds_fp`, and `pm_fp` all adapt with no '
           'other edits.\n'
           '- **Subtraction** — `[la, ha] − [lb, hb] = [la−hb, ha−lb]` with '
           'saturating-sub guarding the lower bound; add `iv_sub` as a method '
           'to `IvArith` and implement it for `Interval`.\n'
           '- **Second instance** — define `type TaggedInterval = | Tagged Interval Bool` '
           'pairing a bound with a confidence flag; implement `IvArith` for it '
           'and observe that `add_iv`, `mul_iv`, and `contains_iv` all work '
           'unchanged — that\'s the polymorphism payoff.\n'
           '- **`spec/05-type-system.md`** — the full typeclass and constraint '
           'specification.\n'
           '- **`doc/phrasebook.md`** — canonical Gallowglass patterns, '
           'including the typeclass dispatch idiom used throughout this notebook.'),
]


def _render_outputs(text: str | None, html: str | None,
                    execution_count: int) -> list[Any]:
    if text is None and html is None:
        return []
    data: dict[str, Any] = {}
    if text is not None:
        data['text/plain'] = text
    if html is not None:
        data['text/html'] = html
    return [v4.new_output('execute_result', data=data,
                          execution_count=execution_count, metadata={})]


def main() -> None:
    nb = v4.new_notebook()
    nb.metadata['kernelspec'] = {
        'name': 'gallowglass',
        'display_name': 'Gallowglass',
        'language': 'gallowglass',
    }
    nb.metadata['language_info'] = {
        'name': 'gallowglass',
        'mimetype': 'text/x-gallowglass',
        'file_extension': '.gls',
        'pygments_lexer': 'haskell',
    }

    evaluator = GallowglassEvaluator()
    exec_count = 0

    for kind, body in CELLS:
        if kind == 'md':
            nb.cells.append(v4.new_markdown_cell(body, id=f"md-{len(nb.cells):02d}"))
            continue
        exec_count += 1
        result = evaluator.eval_cell(body)
        if result.error is not None:
            print(f'WARN: cell {exec_count} errored: {result.error}',
                  file=sys.stderr)
        outputs = _render_outputs(result.value_text, result.value_html,
                                  execution_count=exec_count)
        cell = v4.new_code_cell(source=body, outputs=outputs, id=f"code-{exec_count:02d}")
        cell['execution_count'] = exec_count
        nb.cells.append(cell)

    out_path = os.path.join(os.path.dirname(__file__),
                            '05-interval-arithmetic.ipynb')
    with open(out_path, 'w') as f:
        nbformat.write(nb, f)
    print(f'wrote {out_path}')


if __name__ == '__main__':
    main()
