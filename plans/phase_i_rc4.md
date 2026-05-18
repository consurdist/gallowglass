# Phase I — Toward 1.0.0-rc4

**Status:** rc4-1 ✅ closed; rc4-2 deferred to a follow-up continuation.

**Scope:** close the two remaining self-host codegen gaps that rc3 mapped
but didn't close, so the 1.0 "self-hosted" qualifier can be honestly
claimed.  See `ROADMAP.md §1.0` for the promoted acceptance criteria.

The Python bootstrap already compiles both features correctly — these are
pure byte-identity gaps in the self-host's emission, not user-facing
correctness bugs.

## Status as of 2026-05-16

| Gate | Status | Notes |
|---|---|---|
| `test_typeclass_simple` | ✅ closed | xfail flipped to pass; byte-identical to Python |
| `test_do_notation_simple` | ⏳ deferred | rc4-2; not yet started |
| Phase H `test_compile_self` | ⏳ pending | needs re-run after Compiler.gls changes (long; ~45 min) |
| `compiler/dist/Compiler.plan` regen | ✅ done | MANIFEST updated, sanity tests pass |

## rc4-1 — Typeclass constrained-let codegen  ✅

**Gate test:** `tests/reaver/test_selfhost.py::test_typeclass_simple`
— closed; passes byte-identical to Python.

**What landed (5 commits on `phase-i-1.0.0-rc4`):**

* `TkFatArrow` lex token (`=>` and `⇒`) — was the foundational
  blocker; the bare `=` lexed mid-constraint shredded `skip_ann`.
* `DLet` AST extended to carry a constraint class-name list,
  packed as a `Pair (List Nat) Expr` to keep DLet binary (avoids
  the bootstrap mixed-arity dispatch hazard).
* `extract_constraints_from_ann` walks the type-annotation tokens
  capturing `Class typevar =>` prefix patterns.
* `PConstrained (List Nat) PlanVal` sentinel + `planval_is_constrained`
  / `planval_get_constraints` / `planval_get_constrained_underlying`
  accessors; `cg_var_from_env` transparently unwraps so emission
  paths see the underlying law.
* `cg_compile_constrained_let` wraps the body in extra dict-param
  lambdas (one per method per constraint via `cg_wrap_constraint_lams`),
  compiles via the normal path, and tags with `PConstrained`.
* `cg_collect_class_methods` registry built from `DClass` decls,
  threaded through `cg_pass3_go` as a new parameter.
* `cg_compile_inst_members` emits the single-method dict shortcut
  (`Module.inst_<Class>_<Type>` = the one method's val).
* `cg_compile_app` introspects the EApp root: if its global value
  is `PConstrained`, routes to `cg_compile_constrained_app` which
  walks the chain for user args, resolves the instance dict via
  `cg_resolve_instance_dict`, and applies the assembled chain.
* `cg_find_first_fq_for_law` — canonical-name resolution by law
  NAME nat + ARITY.  Mirrors Python emit's `bind_table[id(val)]`
  semantics for the case where multiple bindings (impl, per-method
  inst, single-method shortcut) share the same PLaw object.

**Documented limitations:**

* Multi-method classes: the single-method dict shortcut path is the
  only one wired up.  Multi-method instance dicts would need a
  record-shape encoding that the call site decomposes.
* Multi-constraint lets: parsing supports a single `Class typevar =>`
  prefix; grouped constraints (`(Eq a, Ord a) =>`) and chained
  constraints (`Eq a => Ord a =>`) aren't yet recognised.
* Type-key inference at call sites: ENat → "Nat" only.  Lets, app
  results, etc. aren't resolved; they'd need a typecheck pass.
* `cg_find_first_fq_for_law` keys on PLaw NAME nat + ARITY rather
  than full structural equality (Reaver.BPLAN.eq is a nat-value
  compare; `op 66 ["Equal"]` would be true deepseq+(==) but isn't
  in `bplan_deps.py` / Reaver.BPLAN's external mod).  Correct for
  the bare-EVar inlining shortcut (same object → same name + arity)
  but could collide if two distinct top-level lets compile to PLaws
  with identical name nats AND arities — extremely unlikely since
  name nats are `encode_name` of the binding name.

## Historical sketch — rc4-1 plan (pre-execution)

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

**Status:** partial progress on `phase-i-1.0.0-rc4` — multiple
sub-issues fixed; one remaining divergence in the `return`-arm law body
(emits `_0` instead of the compiled body for the gate fixture).

### Sub-fixes landed (2026-05-17 session)

Each fix is small and self-contained; all are gated by
``python3 tools/selfcompile.py /tmp/edo_only.gls`` (which now passes
byte-identical) and ``/tmp/effect_fixture.gls`` (still diverges by one
byte in `result_return` law body).

1. **Suffix-named CPS sub-laws.**  Self-host's lifted CPS laws were
   taking the bare outer ``hint`` as their name; Python appends a
   role-specific suffix.  Added inline ``nn_do``, ``nn_cont``,
   ``nn_handle``, ``nn_dispatch``, ``nn_return``, ``nn_body``,
   ``nn_rhs``, ``nn_comp`` constants and wired them through
   ``cg_compile_do`` (outer = ``_do``, inner = ``_cont``, body hint
   = ``_body``, rhs hint = ``_rhs``), ``cg_compile_handle``
   (cps_law = ``_handle``, comp hint = ``_comp``),
   ``cg_compile_dispatch_fn`` (both branches use ``_dispatch``), and
   ``cg_compile_return_fn`` (``_return``).

2. **Top-of-let arity branch swap.**  Both ``cg_compile_do`` and
   ``cg_compile_handle`` had the ``nat_eq (cenv_arity env) 0`` arms
   inverted relative to Python — top-level was wrapping in PPin and
   bapp-applying captures (only valid inside another law), while
   inside-law was returning bare law (no captures applied).  Swapped
   to mirror Python's ``if env.arity == 0: bare else: P(law) + bapp``.

3. **CPS helper-law bodies wrapped with ``cg_bapp``.**  ``cps_compose``,
   ``cps_compose_open``, ``cps_forward_k``, ``cps_pure_law``, and
   ``cps_run_law`` used raw ``PApp`` for every application node.  Emit
   interprets ``App(App(N(1), rhs), body)`` as the let-binding form
   ``_d(rhs)\n  body`` (per spec/04-plan-encoding.md §body context),
   which silently mis-rendered ``_forward_k`` and friends as let-forms.
   Python wraps every node via ``bapp``; matched that here.  Fixed
   the body-shape divergence for the no-arms ``handle`` case.

4. **Eff-op short-name binding removed.**  ``cg_register_eff_ops`` used
   to ``cenv_bind_global`` under both the FQ name *and* the bare op
   name.  Scope resolution sometimes leaves cross-binding bare EVars
   un-qualified (phase_h_handoff.md L289 known-gap), and when it does,
   the bare lookup wins and PNamed-tags the pin with the bare name —
   emit prints ``(#pin inc)`` instead of ``(#pin
   Compiler_Counter_inc)``.  With only the FQ binding present, the
   ``cg_var_from_env`` short-tail fallback resolves bare names to the
   canonical FQ instead.  Python's bind-table dedup achieves the same
   effect via id-based first-wins; this is the GLS-side equivalent.

5. **Wildcard arg in handler arms.**  Added ``tok_eat_ident_or_wild``
   (defined next to ``tok_eat_ident`` for SCC ordering) that accepts
   either an ident or a leading ``_`` token, rewriting the latter to
   ``kw_underscore``.  Without it, ``| inc _ kk → kk 7`` produced a
   sentinel arm with name=0 and ``parse_handle_op_arm`` aborted; the
   enclosing handler ended up with an empty arm list and a degenerate
   dispatch law.  ``parse_handle_op_arm`` now calls
   ``tok_eat_ident_or_wild`` for both the op-arg and resume slots.

6. **Length probe for arm-count dispatch in ``cg_compile_dispatch_fn``.**
   The original ``match op_arms { | Nil → forwarder | _ → main }``
   tripped the bootstrap-codegen mixed-arity wildcard pitfall — every
   non-empty list fell into the Nil arm.  Replaced with
   ``match (nat_eq (length op_arms) 0) { | 0 → main | _ → forwarder }``
   which discriminates safely without relying on the constructor-match
   shape.

### Open: `result_return` body emits `_0`

For ``handle comp { | return rr → body }``, the constructed
``result_return`` law has the right name and arity, but its body is
``PNat 0`` (emits as ``_0``) instead of the compiled ``body``.

**Confirmed via in-tree probes** (replaced ``body_val`` in
``cg_compile_return_fn`` with sentinels in turn):

* ``cg_quote_nat 99 1`` emits ``99`` → the PLaw construction path is
  correct; the law accepts whatever body_val we give it.
* ``cg_quote_nat (cenv_arity ret_env3)`` emits ``99`` (quoted nat) →
  ``ret_env3.arity == 1`` as expected.
* ``ce (ENat 77) ret_env3 ctab ret_name`` emits ``77`` → ``ce`` (the
  compile-function closure parameter) compiles ENat 77 correctly.
* ``cg_quote_nat (expr_tag ret_fn) …`` emits ``2`` → ``ret_fn`` IS an
  ``ELam`` (tag 2).
* ``cg_quote_nat (expr_tag (cg_lam_body ret_fn)) …`` emits ``0`` →
  the body extracted from the ELam has ``expr_tag == 0`` (EVar).
* ``cg_quote_nat (cg_evar_name (cg_lam_body ret_fn)) …`` emits ``0`` →
  it's specifically ``EVar 0`` — the parser-failure sentinel.

So the bug is upstream of cg_compile_return_fn: ``parse_handle_expr``'s
second ``parse_expr rt (tok_tail rest5)`` call (parsing the return-arm
body after ``→``) is returning ``MkPair (EVar 0) rest`` even when the
body is a simple ``ENat 42``.  The first ``parse_expr rt toks`` call in
the same function (parsing ``comp``) works correctly, so it's the
nested-arm-body position that's broken, not parse_expr generally.

This points at a mutual-SCC compilation issue: ``parse_handle_expr``
lives in a 5-member SCC with ``parse_expr``, ``parse_expr_dispatch``,
``parse_handle_arms``, ``parse_handle_op_arm``.  The shared-pin slot
resolution for ``parse_expr`` inside a deeply-nested match arm seems
to be picking up something else.

**Attempted workaround (reverted):** lifting the second parse_expr
into its own helper (``parse_handle_expr_after_ret``) caused
``parse_handle_expr`` to return ``EVar 0`` for the WHOLE expression,
not just the body — likely the helper joined the same SCC and
introduced a different breakage.  A successful workaround probably
needs to break the SCC entirely: move the body parser to a separate
non-recursive helper, or restructure parse_handle_expr to compute
the return body BEFORE the nested match arms via direct let binding.

### Replay loop

```
cat > /tmp/handle_return_42.gls <<'EOF'
let comp : Nat = 1
let result : Nat = handle comp {
  | return rr → 42
}
let main = result
EOF
python3 tools/selfcompile.py -v /tmp/handle_return_42.gls
```

Each iteration ~1s.  Probes can be inserted in ``cg_compile_return_fn``
(near L7160) — the helper-accessor approach (``cg_lam_param`` /
``cg_lam_body`` / ``cg_evar_name``) is the canonical workaround for
the Expr destructuring pitfall.  Once ``result_return`` body matches,
run ``/tmp/effect_fixture.gls`` to confirm end-to-end.

## rc4-2 (original) — Effect handler CPS alignment

**Status:** not started.  Pickup notes for a fresh continuation below.

### Fresh-continuation handoff

1. **Reproduce the byte-diff loop** that worked for rc4-1.  Local
   Reaver is pre-built (no nix needed), so:
   ```
   cat > /tmp/effect_fixture.gls <<'EOF'
   eff Counter {
     inc : Nat → Nat
   }
   let comp : Nat = xx ← inc 1 in inc xx
   let result : Nat = handle comp {
     | return rr → rr
     | inc _ kk → kk 7
   }
   let main = result
   EOF
   python3 tools/selfcompile.py -v /tmp/effect_fixture.gls
   ```
   Each iteration is ~1 second.  The Python reference is also a
   single-line away via the same script.
2. **Reference code:** `bootstrap/codegen.py::_compile_handle` and
   `_compile_do` (post-M13.3 open-continuation protocol; the GLS
   side got the protocol port in M13.4 but didn't reach byte-
   identity).  Self-host equivalents:
   * `cg_compile_handle` (search for `let cg_compile_handle\b`)
   * `cg_compile_do`
   * `cg_compile_dispatch_fn`, `cg_compile_return_fn`,
     `cg_build_handle_dispatch`
   * `cg_register_eff_ops`, `cg_register_effs`
3. **Watch for the bootstrap-codegen pitfalls** documented in
   `CLAUDE.md §"Bootstrap Codegen Pitfalls"`.  rc4-1 was bitten
   twice (binary-single-arm match dispatch in `cg_collect_app_args_go`
   — workaround: use predicate-based form via `cg_expr_is_app` /
   `cg_app_fun` / `cg_app_arg`).  Forward references also bit
   twice (helpers must be defined before callers — use local
   mirrors like `cg_concat_dot_app`, or move definitions earlier).
4. **`fn` is reserved as the ASCII alias for `λ`** — don't name a
   parameter `fn` (the lexer re-lexes it as a second `λ` token
   producing a confusing parse error).  Use `fv` or `f`.

### Three known divergences from Python's emit, per rc3 investigation

**Reference:** `bootstrap/codegen.py::_compile_handle` and
`_compile_do` (post-M13.3 open-continuation protocol; the GLS side
got the protocol port in M13.4 but didn't reach byte-identity).

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
