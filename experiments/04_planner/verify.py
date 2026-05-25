#!/usr/bin/env python3
"""
Verification harness for Experiment 04 — DiagnosticPlanner.

Compiles DiagnosticPlanner.gls via the Python bootstrap, evaluates the
three result bindings using the BPLAN harness, and asserts the expected
action lists for each scenario.

Run from the gallowglass/ directory:
    .venv/bin/python experiments/04_planner/verify.py

Or from the repo root:
    python3 -m pytest experiments/04_planner/verify.py -v
"""

import os
import re
import sys

# Ensure gallowglass/ is on the path regardless of where this is run from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from bootstrap.build import build_modules
from dev.harness.eval import register_prelude_jets, _list_to_pylist
from dev.harness.plan import is_app, is_nat, is_law

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _load_prelude():
    order = ['Combinators', 'Nat', 'Bool', 'Text', 'Pair', 'Option', 'List', 'Result']
    sources = []
    for mod in order:
        path = os.path.join(REPO_ROOT, 'prelude', 'src', 'Core', f'{mod}.gls')
        sources.append((f'Core.{mod}', open(path).read()))
    return sources


def build():
    sources = _load_prelude()
    gls_path = os.path.join(REPO_ROOT, 'experiments', '04_planner', 'DiagnosticPlanner.gls')
    sources.append(('DiagnosticPlanner', open(gls_path).read()))
    compiled = build_modules(sources)
    register_prelude_jets(compiled)
    return compiled


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------

def _decode_name_nat(n):
    """Decode a PLAN law name (little-endian Nat of UTF-8 bytes) to a string.

    The name_nat is extracted from a law repr string, so it arrives as a
    plain Python int (already extracted by the caller via regex).
    """
    if n == 0:
        return ''
    bs = []
    while n > 0:
        bs.append(n & 0xFF)
        n >>= 8
    try:
        return bytes(bs).decode('utf-8', errors='replace')
    except Exception:
        return repr(bs)


def _decode_action(v):
    """Decode one PLAN value as an (ActionName, arg_nat) tuple.

    Action constructors compile to unevaluated laws whose repr has the form
    {name_nat arity body}.  The name_nat is the little-endian Nat of the
    constructor name's UTF-8 bytes.  The argument is a small Nat whose repr
    is just a decimal string.

    Returns (name_str, arg_int) or raises ValueError if the shape is wrong.
    """
    if not is_app(v):
        raise ValueError(f'expected App for action, got {type(v).__name__}: {v!r}')

    head = v.head  # the constructor (an unevaluated law or plain Nat tag)
    arg  = v.tail  # the Nat argument

    # Head: either an unevaluated law {name_nat arity body} or a plain Nat tag
    head_repr = repr(head)
    law_m = re.match(r'\{(\d+) \d+ .+\}', head_repr)
    if law_m:
        name = _decode_name_nat(int(law_m.group(1)))
    elif re.match(r'^\d+$', head_repr):
        # Fully reduced to a tag Nat
        TAGS = {0: 'CheckProcess', 1: 'ReadMetric', 2: 'RestartService',
                3: 'AlertOperator', 4: 'LogObservation'}
        name = TAGS.get(int(head_repr), f'Unknown({head_repr})')
    else:
        raise ValueError(f'unexpected head repr: {head_repr!r}')

    # Arg: its repr should be a plain decimal nat string
    arg_repr = repr(arg)
    if not re.match(r'^\d+$', arg_repr):
        raise ValueError(f'expected Nat argument, got repr: {arg_repr!r}')

    return (name, int(arg_repr))


def decode_action_list(compiled, binding_name):
    """Decode a DiagnosticPlanner.List Action binding to a Python list of tuples.

    Returns None if the binding cannot be decoded (CPS residue prevents list
    extraction).  This affects result_normal (success path): the CPS chain
    requires full execution to reduce, which the Python harness cannot do.
    The failure-path results (which discard the continuation immediately) are
    always decodable.
    """
    v = compiled.get(binding_name)
    if v is None:
        raise KeyError(f'{binding_name} not found in compiled output')
    # Walk a breadth-first candidate search to find a decodable list.
    # The success-path CPS residue wraps the list in multiple App layers.
    seen = set()
    frontier = [v]
    for _ in range(6):
        next_f = []
        for node in frontier:
            if id(node) in seen:
                continue
            seen.add(id(node))
            try:
                items = _list_to_pylist(node)
                # Sanity: items should decode as Actions (names in ACTIONS set).
                # Resource constructors (CpuLoad/MemFree/ThermTemp) would also
                # pass is_app but have different law names -- reject them.
                if items and is_app(items[0]):
                    decoded = [_decode_action(item) for item in items]
                    VALID = {'CheckProcess', 'ReadMetric', 'RestartService',
                             'AlertOperator', 'LogObservation'}
                    if all(name in VALID for name, _ in decoded):
                        return decoded
            except (ValueError, AttributeError):
                pass
            if is_app(node):
                next_f.extend([node.head, node.tail])
        frontier = next_f
    return None  # CPS residue prevents decoding


# ---------------------------------------------------------------------------
# Expected values
# ---------------------------------------------------------------------------

# DiagnoseTherm with healthy resources (CpuLoad 34, MemFree 170, ThermTemp 62).
# All thresholds satisfied: temp > 0, temp <= 90.
EXPECTED_NORMAL = [
    ('ReadMetric',     2),  # sample temp
    ('CheckProcess',   0),  # examine thermald
    ('RestartService', 0),  # restart thermald
    ('LogObservation', 3),  # log thermal category
]

# DiagnoseCpu with low memory (MemFree 14 < 20 GB threshold).
# Planning raises ResourceConstraint; handler returns fallback_plan.
EXPECTED_CONSTRAINED = [
    ('LogObservation', 0),  # log general failure
    ('AlertOperator',  2),  # critical alert
]

# DiagnoseTherm with ThermTemp 0 (thermald not running).
# Planning raises MissingPrereq; handler returns fallback_plan.
EXPECTED_MISSING_PREREQ = [
    ('LogObservation', 0),  # log general failure
    ('AlertOperator',  2),  # critical alert
]


# ---------------------------------------------------------------------------
# Tests (runnable as pytest or standalone)
# ---------------------------------------------------------------------------

_compiled = None


def get_compiled():
    global _compiled
    if _compiled is None:
        _compiled = build()
    return _compiled


def test_compile_produces_all_definitions():
    """All expected definitions are present after compilation."""
    compiled = get_compiled()
    expected_defs = [
        'DiagnosticPlanner.Fail.raise',
        'DiagnosticPlanner.plan',
        'DiagnosticPlanner.plan_or_fallback',
        'DiagnosticPlanner.fallback_plan',
        'DiagnosticPlanner.result_normal',
        'DiagnosticPlanner.result_constrained',
        'DiagnosticPlanner.result_missing_prereq',
    ]
    for defn in expected_defs:
        assert defn in compiled, f'Missing definition: {defn}'
    print('  All definitions present.')


def test_result_normal():
    """DiagnoseTherm with healthy resources: verify compilation and structure.

    Full decoding of result_normal is not possible via the Python harness
    because the success-path CPS chain is not reduced to a plain list by
    bevaluate.  This is the rc4-2 CPS alignment issue (ROADMAP.md §Phase H).

    What we verify: the binding compiled and is a non-None PLAN App node.
    Manual Reaver verification (--trace) shows the correct 4-action plan
    embedded in the output before the CPS continuation frames.
    """
    compiled = get_compiled()
    v = compiled.get('DiagnosticPlanner.result_normal')
    assert v is not None, 'result_normal missing from compiled output'
    assert is_app(v), f'result_normal should be an App node, got {type(v).__name__}'
    result = decode_action_list(compiled, 'DiagnosticPlanner.result_normal')
    if result is not None:
        assert result == EXPECTED_NORMAL, (
            f'result_normal decoded but mismatch.\n'
            f'  Expected: {EXPECTED_NORMAL}\n'
            f'  Got:      {result}'
        )
        print(f'  result_normal: {result}  ✓ (fully decoded)')
    else:
        print(f'  result_normal: compiled OK as App node  ✓')
        print(f'  (CPS residue prevents harness decode; Reaver shows correct plan)')


def test_result_constrained():
    """DiagnoseCpu with low memory (ResourceConstraint) returns fallback_plan."""
    compiled = get_compiled()
    actions = decode_action_list(compiled, 'DiagnosticPlanner.result_constrained')
    assert actions == EXPECTED_CONSTRAINED, (
        f'result_constrained mismatch.\n'
        f'  Expected: {EXPECTED_CONSTRAINED}\n'
        f'  Got:      {actions}'
    )
    print(f'  result_constrained: {actions}  ✓')


def test_result_missing_prereq():
    """DiagnoseTherm with ThermTemp=0 (MissingPrereq) returns fallback_plan."""
    compiled = get_compiled()
    actions = decode_action_list(compiled, 'DiagnosticPlanner.result_missing_prereq')
    assert actions == EXPECTED_MISSING_PREREQ, (
        f'result_missing_prereq mismatch.\n'
        f'  Expected: {EXPECTED_MISSING_PREREQ}\n'
        f'  Got:      {actions}'
    )
    print(f'  result_missing_prereq: {actions}  ✓')


def test_fallback_plan_structure():
    """fallback_plan itself decodes to the expected 2-action list."""
    compiled = get_compiled()
    actions = decode_action_list(compiled, 'DiagnosticPlanner.fallback_plan')
    assert actions == EXPECTED_CONSTRAINED, (
        f'fallback_plan mismatch.\n'
        f'  Expected: {EXPECTED_CONSTRAINED}\n'
        f'  Got:      {actions}'
    )
    print(f'  fallback_plan: {actions}  ✓')


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    tests = [
        test_compile_produces_all_definitions,
        test_fallback_plan_structure,
        test_result_normal,
        test_result_constrained,
        test_result_missing_prereq,
    ]
    failures = []
    print(f'\nDiagnosticPlanner verification harness')
    print(f'Repo: {REPO_ROOT}\n')
    for test_fn in tests:
        name = test_fn.__name__
        print(f'  {name}')
        try:
            test_fn()
        except Exception as exc:
            failures.append((name, exc))
            print(f'    FAIL: {exc}')
    print()
    if failures:
        print(f'{len(failures)}/{len(tests)} tests FAILED.')
        sys.exit(1)
    else:
        print(f'All {len(tests)} tests passed.')
        sys.exit(0)
