# Phase I — Toward 1.0.0-rc4

**Status:** in progress.
**Scope:** close the two remaining self-host codegen gaps that rc3 mapped
but didn't close, so the 1.0 "self-hosted" qualifier can be honestly
claimed.  See `ROADMAP.md §1.0` for the promoted acceptance criteria.

The Python bootstrap already compiles both features correctly — these are
pure byte-identity gaps in the self-host's emission, not user-facing
correctness bugs.

## rc4-1 — Typeclass constrained-let codegen

**Gate test:** `tests/reaver/test_selfhost.py::test_typeclass_simple`
(currently xfail; flip to pass).

**Reference:** `bootstrap/codegen.py::_compile_constrained_let` and
`_compile_constrained_app` (~200 LoC together).  Also
`_constrained_lets` registry and `_class_methods`/`_instance_dicts`
state on the `Compiler` object.

Three coupled changes to `compiler/src/Compiler.gls`:

1. **Arity adjustment for constrained lets.**
   Source: `let same : ∀ a. Eq a => a → a → Nat = λ x y → eq x y`.
   Python adds one dict-param per constraint, so the compiled law for
   `same` is arity 3 (dict + 2 user params) and the dict shows up as
   `_3` from inside the body.  Class-method references inside the body
   resolve to dict-projection (`_3` for a single-method class, or
   `(_3 idx)` for multi-method) rather than to global symbol lookup.

2. **Single-method dict shortcut emission.**
   When a class has exactly one method, Python emits
   `Compiler_inst_Eq_Nat` as a direct alias to the method law, not as
   a one-element record.  Detect arity-1 classes in
   `cg_compile_inst_members` and emit the shortcut.

3. **Call-site dict insertion.**
   At `same 7 7`, Python's `_compile_constrained_app` recognises that
   `same` is in `_constrained_lets` and inserts the resolved instance
   dict as the first arg: `same inst_Eq_Nat 7 7`.  Dict resolution
   uses type inference at the call site (see `_infer_type_key` /
   `_type_to_instance_key`).  For the gate test, Nat literals make
   the dict resolution trivial — the harder cases (lets, application
   results) can fall back to surface-syntax heuristics for now since
   the bootstrap typecheck pass isn't in the self-host.

**Verification strategy:**
- Add a tiny harness that compiles the gate-test source via both
  Python and the self-host (run through `python3 tools/selfcompile.py`
  on a small typeclass fixture).
- Diff bytes; fix the first divergence; repeat.
- Once the small fixture is byte-identical, run the Phase H compile-
  self gate to confirm we haven't regressed `Compiler.gls` itself
  (none of `Compiler.gls`'s own bindings are constrained, so it
  should be a no-op there).

## rc4-2 — Effect handler CPS alignment

**Gate test:** `tests/reaver/test_selfhost.py::test_do_notation_simple`
(currently xfail; flip to pass).

**Reference:** `bootstrap/codegen.py::_compile_handle` and
`_compile_do` (post-M13.3 open-continuation protocol; the GLS side
got the protocol port in M13.4 but didn't reach byte-identity).

Three known divergences from Python's emit, per rc3 investigation:

1. **Extra captured-slot indirections in the dispatch chain.**
   Self-host's lifted continuation laws have one or two extra slots
   that Python doesn't.  Audit `cg_compile_dispatch_fn` and
   `cg_build_handle_dispatch` capture-set computation against
   `_compile_handle`'s — likely the self-host is capturing the
   handler's own bound names where Python uses sentinel substitution.

2. **Cross-references emit as `(#pin inc)` rather than the FQ
   `Compiler_Counter_inc`.**  The eff-op name resolution is using
   the bare op-name nat instead of the scope-qualified one.  Likely
   `cg_register_eff_ops` is storing the wrong key, or
   `cg_compile_dispatch_fn`'s arm-body compile is looking it up by
   bare name.

3. **Mis-numbering of let-binding slots inside lifted continuations.**
   The `_5((_2 _3))` shapes in observed output show let-bindings
   allocating slots inconsistent with Python's numbering — `cg_compile_do`'s
   inner-continuation param order (`[caps, k_open_outer, dispatch, x]`)
   may need a tweak, or the let-allocator inside the lifted law is
   off by one.

**Verification strategy:** same diff-driven loop as rc4-1 against a
single small handle/do fixture.

## After both gaps close

1. **Re-bootstrap `compiler/dist/Compiler.plan`** via Python — the
   seed must reflect the new Compiler.gls source.  Update
   `compiler/dist/MANIFEST.json` (BLAKE3 + `size_bytes` via
   `os.path.getsize`, not `len(string)` — Compiler.gls has Unicode).
2. **Run Phase H compile-self gate** (`GALLOWGLASS_RUN_COMPILE_SELF=1
   pytest tests/reaver/test_selfhost.py::TestPhaseHFixedPoint`).
   Expected runtime ~20-45 min under Reaver no-jets.
3. **Flip the two xfails to pass** in `tests/reaver/test_selfhost.py`.
4. **Tag v1.0.0-rc4**, push, verify CI green across all matrix
   entries.
5. **Red-team review:** dispatch Dwarf (failure modes), Hobbit
   (overengineering), Elf (naming + long-term shape), Gnome (actual
   behavior), Angel (transparency/documentation) in parallel against
   the rc4 tag.  Address findings before tagging 1.0 final.
