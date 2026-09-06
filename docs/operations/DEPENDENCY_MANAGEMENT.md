# Dependency management

## Two tiers, deliberately unequal

| Tier | Contents | Policy |
| --- | --- | --- |
| **Runtime** | Nothing | Zero dependencies, enforced by a test |
| **Development** | `ruff` | Exact version *and* SHA-256 digest, per platform |

The runtime has no dependencies because code whose job is to refuse actions
should not inherit a supply chain. Every package in a governance path is an actor
that can change what "no" means during a routine upgrade.
[`tests/contract/test_hermeticity.py`](../../tests/contract/test_hermeticity.py)
parses every module under `src/` and fails if anything outside the standard
library is imported, so the property cannot decay quietly.

The cost is real and is documented in
[ADR-0005](../adr/0005-zero-runtime-dependencies.md): the JSON Schema validator
is hand-rolled at about 240 lines and implements a keyword subset.

---

## Why the lockfiles are split by platform

Wheel digests are platform-specific. A single cross-platform lockfile either
drops the hashes — which defeats the point — or fails to install somewhere.

```
requirements/
  dev.in                  the pins, human-edited
  dev.linux.lock.txt      manylinux + musllinux + sdist digests
  dev.macos.lock.txt      macOS arm64 + sdist digests
```

Both locks include the sdist digest so an environment with no matching wheel can
still build from source under `--require-hashes`.

---

## What `--require-hashes` buys

```console
pip install --require-hashes -r requirements/dev.linux.lock.txt
```

Under this flag pip refuses any artifact whose digest is not listed. A
compromised index, a substituted wheel, or a re-uploaded version fails the
install instead of running in CI with the same version number.

Without hashes, `ruff==0.16.6` means "whatever the index currently serves under
that name". With them, it means one specific set of bytes.

---

## Adding or updating a dependency

1. Edit `requirements/dev.in`. Pin an exact version — `check_lockfiles.py`
   rejects a range.
2. Regenerate both lockfiles with real digests from the index:

```console
python3 - <<'PY'
import json, urllib.request
name, version = "ruff", "0.16.6"
urls = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json"))["urls"]
for f in urls:
    print(f["filename"], f["digests"]["sha256"])
PY
```

   Take the `manylinux` + `musllinux` + sdist digests for the Linux lock, and the
   `macosx_11_0_arm64` + sdist digests for the macOS lock.

3. Verify:

```console
make audit                                                   # drift check
pip install --require-hashes -r requirements/dev.macos.lock.txt   # real install
```

The second command is the one that matters. A lockfile that has never been
installed under `--require-hashes` is a lockfile nobody has checked, which is why
[`lockfile-check.yml`](../../.github/workflows/lockfile-check.yml) performs a real
install on both platforms rather than only diffing files.

---

## What the drift check catches

[`scripts/check_lockfiles.py`](../../scripts/check_lockfiles.py) fails when:

- A package in `dev.in` is missing from a lock.
- Versions disagree between `dev.in` and a lock.
- A package is pinned in a lock with no `--hash` entry.
- A lock contains a package `dev.in` does not declare.
- A pin is not an exact version.

The failure it exists to prevent is quiet: someone bumps a pin, forgets one of
the two locks, and CI keeps installing the old version on one platform for
months. Nothing breaks loudly, and the lockfiles stop meaning anything.

---

## Dependabot

Dependabot watches `requirements/` and the GitHub Actions used by the workflows.
It opens the version bump; the lockfile check then fails until both locks are
regenerated with real hashes.

That friction is the design. An automated update should not be able to weaken the
pinning it is updating, and a bot that could regenerate hashes on its own would
be a bot that could change what gets installed.
