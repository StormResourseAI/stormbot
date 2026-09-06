# ADR-0005 — Zero runtime dependencies, and what it cost

**Status:** Accepted · **Date:** 2026-09-06

## Context

The obvious dependency list for this repository is short and entirely reasonable:
`jsonschema` for registry validation, `pydantic` for typed models, `pyjwt` for
approval tokens, `pytest` for the suite. Each is mature, well maintained, and
better at its job than anything written here.

The counter-argument is narrow but specific. This code's entire purpose is to
decide whether an action is permitted. Every package in that path is an actor
that can change what "no" means, and it changes during a routine `pip install`
that nobody reads the diff of. A supply-chain compromise in a logging library
gets you logs; a supply-chain compromise in a governance library gets you
authority.

## Decision

`src/stormbot` imports only the standard library.
[`tests/contract/test_hermeticity.py`](../../tests/contract/test_hermeticity.py)
parses every module with `ast` and fails if anything outside
`sys.stdlib_module_names` appears — so the property cannot decay quietly through
one convenient import.

The test suite is also stdlib-only, using `unittest`. Development tooling
(`ruff`) is permitted, hash-pinned, and never imported by the runtime.

## Consequences

**Good.** The runtime supply chain is CPython. CI installs nothing for the test
job, so the suite cannot fail because an index was slow — 141 tests in 0.15
seconds with no resolution step. `pip install stormbot` pulls one package. There
is no dependency-upgrade treadmill on the code that decides whether to text a
stranger.

**The cost, stated plainly.**

**A hand-rolled JSON Schema validator,** about 240 lines in
[`schema.py`](../../src/stormbot/assurance/schema.py), implementing a keyword
subset. It has no `anyOf`, no `oneOf`, no remote `$ref`, and no format registry.
It is worse than `jsonschema` in every respect except the one that motivated it.

The mitigation is that it raises `UnsupportedSchemaKeyword` on anything it does
not implement, rather than ignoring it. Silently skipping an unknown keyword
would mean a schema author writing `anyOf` gets a document that validates against
nothing — the worst possible failure for a validation library, because it looks
like success. Failing loudly is what makes a subset safe rather than permissive.

**`unittest` instead of `pytest`.** More ceremony: no fixtures, no
parametrization, no `assert` rewriting. `subTest` covers most parametrization
needs adequately. This is the cost paid most often, on nearly every test written.

**Manual HMAC instead of a JWT library.** For a four-field token, 130 lines has a
smaller attack surface than a JWT library — but only because the token is that
simple. This would be the wrong call for anything with real claim semantics.

## When this would be the wrong decision

This is a narrow choice and it does not generalize. It would be wrong for:

- **A larger surface.** Reimplementing HTTP, a database driver, or a template
  engine is not principled, it is reckless. The line is roughly where the
  reimplementation exceeds what one person can review.
- **A team that rotates.** A hand-rolled validator is a maintenance burden borne
  by whoever inherits it, and "we wrote our own" ages badly.
- **Anything cryptographic beyond stdlib primitives.** `hmac` and `hashlib` are
  fine. Implementing a cipher, a signature scheme, or a key-exchange protocol is
  not, ever.
- **Code that is not in a governance path.** The reasoning is specifically about
  code that decides whether something is permitted. It does not extend to an
  adapter layer.

The general form of the argument is not "dependencies are bad". It is that the
acceptable dependency count for a component is a function of what that component
is trusted to decide, and for this one the answer happens to be zero.

## Alternatives considered

**Vendoring `jsonschema`.** Same supply-chain exposure at import time, worse
update story, and the code is in the repository without being reviewed.

**Optional dependencies with a stdlib fallback.** Two code paths for the
validation logic, which means the one CI exercises is not necessarily the one
production runs. Worse than either option alone.

**Dependencies only in the assurance half.** Defensible — the assurance code runs
in CI, not in the request path — and rejected for a smaller reason: one
consistent rule with an enforcing test is easier to hold than two rules with a
boundary that has to be adjudicated on every PR.
