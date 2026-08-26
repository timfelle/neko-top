# Neko-TOP Release Plan {#release-plan}

## Purpose {#release-plan-purpose}

This plan defines the one-time setup and recurring process for reproducible
Neko-TOP source releases. It keeps `main` linear with one squash commit per
public release, keeps open `develop` pull requests valid, selects release
content explicitly, and records the exact external dependencies used to build
and validate every release.

The plan applies to `ExtremeFLOW/Neko-TOP` only. Neko is an external dependency;
this plan does not alter Neko's upstream release policy.

## Branch Model {#release-plan-branches}

Neko-TOP uses exactly four persistent branch types.

| Branch type          | Purpose                                     | Update policy                                                                                                                                                             |
| -------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main`               | Latest released Neko-TOP state.             | One squash commit per release; linear; no direct push, merge commit, or rebase merge.                                                                                     |
| `release/vX.Y.Z`     | Final promotion branch for version `X.Y.Z`. | Created from the approved RC and rebased onto the immediately previous release commit in `main`; the only permitted source for a `main` release PR.                       |
| `release/vX.Y.Z-rcN` | Candidate `N` for version `X.Y.Z`.          | Starts at the immediately previous tagged `main` release; contains only selected cherry-picks from `develop`, release fixes, and release metadata; immutable once tagged. |
| `develop`            | Continuous feature integration branch.      | User changes enter through squash-merged PRs. After a release, it receives one signed `--no-ff` merge of `main`, preserving open PR ancestry.                             |

No other persistent branch namespace is part of the release model. Internal
provenance is represented by immutable tags, not additional branches.

## Tag Policy {#release-plan-tags}

- `vX.Y.Z` is the canonical public release tag. It is a signed annotated tag
  on the sole squash commit for that release in `main`.
- `vX.Y.Z-rcN` is a signed annotated candidate tag on the exact head of
  `release/vX.Y.Z-rcN` that passed candidate validation. A GitHub pre-release
  points to this tag.
- `release-source/vX.Y.Z` is an internal signed annotated provenance tag on
  the head of `release/vX.Y.Z` before the branch is squash-merged and deleted.
  It preserves the individual replayed commits behind the public squash.
- `release-bootstrap` is an internal signed tag on the initial `main` base for
  the first public release.
- Tags are immutable: they must never be moved, deleted, or repointed. GitHub
  Releases and source archives always reference `vX.Y.Z`, never
  `release-source/vX.Y.Z`.

```text
main:       vPREVIOUS --- [single squash: Release vX.Y.Z] --- vX.Y.Z
                              ^
release/vX.Y.Z:  vPREVIOUS --- replayed selected commits --- metadata
                              ^
release/vX.Y.Z-rc1: vPREVIOUS --- selected cherry-picks --- metadata
release/vX.Y.Z-rc2:                         rc1 --- release fixes --- metadata

 develop: ... -- feature PRs --+-- newer feature PRs
                               \-- [--no-ff merge main after vX.Y.Z]
```

The `main` to `develop` merge is intentional. It is the sole exception to
normal squash-only updates on `develop`; it does not rewrite `develop` or any
contributor branch.

## Release Selection {#release-plan-selection}

1. Before a release train starts, the previous public tag, `vPREVIOUS`, must
   resolve to the current `main` tip. The first release uses
   `release-bootstrap` as its initial base.
2. Create `release/vX.Y.Z-rc1` directly at `vPREVIOUS`, never at the moving
   `develop` head.
3. A release manager explicitly selects the already green squash-merge commits
   from `develop` that belong in the release and cherry-picks them in recorded
   order.
4. Record every selected change in a versioned release manifest, including the
   source SHA, pull request number, title, patch ID, ordering, and candidate
   cherry-pick SHA. Do not infer release contents from an unbounded Git range.
5. Release fixes must first land in `develop` through the normal squash-merge
   process, then be cherry-picked into the next RC. This prevents RC-only code
   from drifting from `develop`.
6. Create `release/vX.Y.Z-rcN+1` from the preceding candidate branch. Do not
   modify a tagged candidate branch or candidate tag.
7. Create the final `release/vX.Y.Z` from the approved final RC. Replay or
   force-rebase its explicit `vPREVIOUS..final-RC` commit sequence onto
   `vPREVIOUS`, consolidating release metadata into one metadata commit.
8. The final branch must contain exactly the manifest-selected feature and fix
   commits, in order, plus one release-metadata commit. Its tree must be
   identical to the approved final RC tree. Any mismatch fails closed.

## Recurring Release Procedure {#release-plan-procedure}

1. **Cut RC:** A release manager starts `cut-rc` with a manually validated
   SemVer target. The workflow verifies that `main == vPREVIOUS`, no train is
   active, and selected changes are merged and green on `develop`; it then
   creates `release/vX.Y.Z-rc1` at `vPREVIOUS`.
2. **Freeze metadata:** Cherry-pick selected commits in manifest order. Add or
   update the Neko-TOP version, dependency lock, changelog, and manifest; tag
   the result as `vX.Y.Z-rc1`.
3. **Validate RC:** Run the full release suite against the exact candidate tag
   SHA: formatting, documentation, linting, compilation and unit tests,
   scripts, examples, Valgrind, relevant schema checks, dependency-lock and
   signature validation, and a clean source-archive build/install test.
4. **Iterate RCs:** When a fix is needed, merge it into `develop` first, create
   the next candidate from the previous candidate, cherry-pick the fix, update
   metadata if needed, tag it, and rerun the same full suite.
5. **Promote:** `promote-release` verifies the approved RC checks, selection
   manifest, `main == vPREVIOUS`, and release-train state. It creates
   `release/vX.Y.Z`, records original-to-final SHA mappings, and opens the
   final release PR after final validation.
6. **Merge main:** Require approval by a maintainer other than the release
   manager who prepared the branch. Squash-merge `release/vX.Y.Z` into `main`.
   Before public tagging, verify that `main` advanced by exactly one commit,
   that its parent is `vPREVIOUS`, and that its tree equals the final release
   branch tree.
7. **Publish:** Before deletion, create `release-source/vX.Y.Z` at the final
   release-branch head. Create the public `vX.Y.Z` tag on `main`, publish the
   GitHub Release and source archive, then deploy documentation from the tagged
   `main` SHA.
8. **Synchronise develop:** Fetch the current protected `develop` tip and make
   a signed local `git merge --no-ff main`. Resolve conflicts only according to
   the documented release metadata and lock policy, run the develop gate, and
   push the merge as a normal non-force update through the Release Managers
   exception. Notify authors of open pull requests; no rebase is mandatory.
9. **Clean up:** Delete the final and candidate release branches only after
   tags, artifacts, documentation, and the `develop` synchronisation have
   validated. Keep all tags immutable.
10. **Abandonment:** If a release train is abandoned, close only its release
    branches. Do not modify `develop`; candidate fixes already entered it
    through normal PRs.

## First Release Bootstrap {#release-plan-bootstrap}

1. [ ] Create a signed `release-bootstrap` tag at the existing protected
       `main` tip. It is not a public version.
2. [ ] Check whether `main` is already an ancestor of `develop`.
3. [ ] If it is not, perform one reviewed signed `git merge --no-ff main` into
       `develop` before cutting the first RC. Do not rebase or force-update
       `develop`.
4. [ ] Use `release-bootstrap` as `vPREVIOUS` for the first candidate. Every
       later candidate starts from the preceding public `vX.Y.Z` tag.

## GitHub Controls and Release Authority {#release-plan-controls}

1. [ ] Form a Release Managers team with at least two maintainers. Only this
       team may bypass the `develop` ruleset for the documented signed
       `main` to `develop` synchronisation merge. Do not create a persistent
       automation credential with broad bypass permissions.
2. [ ] Select GPG or SSH signing for release-manager commits and annotated
       release, candidate, bootstrap, and provenance tags. Document trusted
       keys, key rotation, and revocation.
3. [ ] Configure repository merge settings to offer squash merging only in the
       GitHub PR UI. Disable merge commits and rebase merges in the UI.
4. [ ] Configure a `main` ruleset requiring PRs, the full release gate,
       CODEOWNERS and required reviews, resolved threads, linear history, and
       no direct push, force push, or deletion. It must accept only
       `release/vX.Y.Z` as a release PR source.
5. [ ] Configure a `develop` ruleset requiring ordinary PRs, squash merges,
       and the develop gate, with no force pushes. Allow the narrowly scoped
       Release Managers exception only for the signed synchronisation merge.
6. [ ] Restrict creation and updates of `release/v*` branches to Release
       Managers. Workflow validation must ensure a tagged candidate has not
       subsequently changed.
7. [ ] Protect `v*`, `release-bootstrap`, and `release-source/*` tags from
       update or deletion, and restrict their creation to Release Managers.
8. [ ] Add `CODEOWNERS` for release workflows, locks, setup scripts, CMake
       packaging, and release documentation.
9. [ ] Enable secret scanning, push protection, Dependabot alerts, explicit
       least-privilege workflow permissions, and protected manual dispatch.
10. [ ] Use a non-cancelling `release-train` concurrency lock for cut,
        validation, and promotion. Every action that writes a ref must recheck
        the expected branch and tag SHA first.

## CI Gate Setup {#release-plan-ci-gates}

1. [ ] Repair `.github/workflows/pr_main.yml`. It currently references
       nonexistent reusable workflows and does not reliably fail on
       documentation errors. Use the existing reusable workflow interfaces,
       pass all lock-derived version inputs, aggregate with `if: always()`, and
       fail for every required result.
2. [ ] Create a reusable `release-gate` for candidate and final branches. It
       must be at least as strict as `pr_develop.yml`: formatting,
       documentation, linting, compilation and tests, scripts, examples,
       Valgrind, source-archive installation, dependency-lock, manifest,
       signature, and tree checks.
3. [ ] Add `validate-release-source` to `main` PR validation. It must check
       SemVer branch and tag names, head/base relationship, previous-main SHA,
       manifest lock digest, selected commit list, metadata-only file changes,
       and safe handling of workflow inputs.
4. [ ] Keep the merge queue disabled for `main`. Decide separately whether to
       use it for `develop`; if enabled, every required workflow must support
       `merge_group` and use stable required-check names.
5. [ ] Pin every GitHub Action to a reviewed full commit SHA and remove
       `@latest`. Use `ubuntu-24.04` rather than `ubuntu-latest`, record runner
       and package inventories, and use a pinned container for CPU source
       release verification where practical.
6. [ ] Repair documentation publication. The current callable documentation
       workflow has a push-only deployment condition; add an explicit trusted
       release publication path for the tagged `main` SHA.

## Dependency and Environment Lock {#release-plan-dependencies}

1. [ ] Add a root `dependencies.lock.json` and a per-release manifest. For
       every dependency record its purpose, source URL, upstream release tag or
       version, immutable source SHA or archive digest, SHA-256, licence source,
       acquisition method, and enabled build features.
2. [ ] Audit every fetch surface: `scripts/dependencies.sh`, `setup.sh`,
       composite setup actions, documentation `FetchContent`, Python and pip
       dependencies, test helpers, archives, and transitive Neko inputs.
       Validation must fail on an unmanaged clone or download.
3. [ ] Lock Neko, JSON-Fortran, pFUnit, HDF5, GSLIB, optional Nek5000,
       ParMETIS, and every selected profile dependency to an obtainable public
       release. Moving references such as `master`, `develop`, `neko-top`, and
       `latest` are forbidden in release and `main` locks.
4. [ ] If a required compatible dependency state has no public release, block
       the Neko-TOP release or use an approved immutable, licence-audited
       internal mirror. Do not silently lock a transient branch head.
5. [ ] Resolve tags to peeled commits, fetch detached SHAs, and verify archive
       checksums before extraction. Replace the current mutable, checksum-free
       ParMETIS download with an official immutable artifact or approved mirror.
6. [ ] Refactor setup scripts and composite actions to consume the lock and
       reject divergent hidden defaults. Maintain a clearly named mutable
       development-compatibility manifest for upstream testing; release and
       `main` workflows must reject it.
7. [ ] Record release-CI provenance: OS image, compiler, MPI, CMake, device
       toolchains, build flags, package inventory, and Action SHAs. Retain or
       mirror third-party source artifacts subject to the applicable licences.
8. [ ] Generate an SPDX or CycloneDX SBOM, provenance, and third-party NOTICE.
       Schedule dependency and vulnerability review; corrections are delivered
       as ordinary patch releases.

### Dependency Version-Link Contract {#release-plan-dependency-links}

Neko-TOP's SemVer version is independent of its dependencies' version numbers.
A Neko-TOP release is linked to exact external releases through the committed
`dependencies.lock.json`, not by requiring matching version numbers.

- At `cut-rc`, freeze the lock in the candidate metadata commit. The release
  manifest records the lock digest alongside the Neko-TOP version and candidate
  SHA.
- All candidates for the same Neko-TOP target version use the same lock unless
  a deliberate dependency update is made. That update requires `rcN+1` and a
  complete rerun of the RC suite.
- Final `vX.Y.Z` on `main` contains the approved lock. The GitHub Release
  publishes both lock and manifest so users can identify and verify the exact
  external releases used to build and test it.
- CI and the normal supported setup path consume the lock, fetch detached
  source SHAs, and verify artifacts. A user-supplied dependency directory that
  differs from the lock is rejected or explicitly reported as unsupported and
  non-reproducible.
- A mutable development compatibility manifest may track upstream branches. It
  is forbidden for RC, final-release, and published-source-archive builds. A
  broader documented Neko compatibility range is separately tested and never
  replaces the exact reproducible release lock.

## Release CI Limits and Test Tiers {#release-plan-ci-limits}

1. [ ] Make bounded CPU tests required on GitHub-hosted Linux runners:
       pFUnit and CTest unit tests, low-rank MPI tests, formatting,
       documentation, linting, CPU Valgrind regression, short MMA regression,
       shortened example runs, lock validation, and a clean source-archive
       build/install. End users do not need to run these tests manually.
2. [ ] Wire the complete CPU release suite explicitly. `check_scripts.yml`
       currently runs short MMA and unit coverage, `check_valgrind.yml` runs
       CPU Valgrind, and `check_examples.yml` shortens then runs all examples;
       the release gate must call every intended suite directly.
3. [ ] Treat sensitivity regression as an RC or release lane, not an ordinary
       PR gate. It is opt-in through `NEKO_TOP_RUN_SENSITIVITY_REGRESSION`, uses
       two MPI ranks, serialises cases with a CTest resource lock, and currently
       permits up to 1,800 seconds for six cases plus 5,400 seconds for
       `passive_scalar`. Run it in a dedicated release job or split it across
       isolated jobs.
4. [ ] Keep CUDA and HIP compile coverage on GitHub-hosted CI, but do not claim
       runtime, memory, multi-GPU, large-rank MPI, performance, or hardware
       validation there. Standard GitHub-hosted runners do not provide usable
       CUDA or HIP accelerators.
5. [ ] Categorise each release test as `hosted-required`,
       `self-hosted-required`, or `advisory`. The Release Manager owns
       collecting required self-hosted or HPC evidence for the exact RC or final
       SHA. User testing is supplementary compatibility evidence, not a release
       gate replacement.
6. [ ] Run scalability and performance certification on controlled
       self-hosted/HPC hardware, not ephemeral hosted VMs. Publish the machine,
       compiler, MPI, and device provenance with that release evidence.

## Release Workflows and Source Artifacts {#release-plan-workflows}

1. [ ] Add protected, manually dispatched `cut-rc`, `rc-validate`, and
       `promote-release` workflows. They must validate inputs, create only the
       four permitted branch forms, generate manifests, use full Git history,
       and avoid raw `develop` range rebases and token event chaining.
2. [ ] Add a reviewed signed human finalisation and synchronisation script,
       executed from a clean clone. It verifies final main/tree/tag invariants,
       signs tags, publishes release assets and documentation, performs the
       normal no-fast-forward `main` to `develop` merge, validates it, and
       writes an auditable transcript. It must be idempotent and abort on an
       unexpected pre-existing ref or asset.
3. [ ] Generate a source archive from tagged `main`. Include the lock,
       manifest, NOTICE, licence, version metadata, and build instructions.
       Build it in an isolated checkout with no `.git`, workspace `external/`,
       or developer-path reuse.
4. [ ] Attach the source archive, `SHA256SUMS`, lock, SBOM, provenance, and
       signature or attestation to the GitHub Release.

## Communication and Sustained Validation {#release-plan-communication}

1. [ ] Add changelog and release-note conventions plus a release PR template
       covering SemVer rationale, selected `develop` PRs, compatibility,
       dependency-lock changes, RC evidence, and known issues.
2. [ ] Publish a source-release support matrix, installation, upgrade, and
       downgrade guidance, governance and Release Manager roles, security
       reporting and vulnerability response, deprecation policy, and optional
       scientific citation metadata.
3. [ ] Run scheduled clean-source smoke tests using the published lock. Alert
       on regressions but never modify a published release; use an ordinary
       patch release for corrections.

## Verification Checklist {#release-plan-verification}

1. [ ] In a disposable fork, complete two releases while test feature PRs stay
       open across each `main` to `develop` synchronisation merge. Verify that
       no PR needs history rewriting and that its base remains an ancestor of
       current `develop`.
2. [ ] Verify every RC starts at the exact previous `main` release; each
       included change maps to one green manifest-selected `develop` squash
       commit; and excluded `develop` work never appears in the final branch.
3. [ ] Verify the final branch contains exactly selected replayed commits plus
       one metadata commit, its tree equals the final RC tree,
       `release-source/vX.Y.Z` points to its head, and `main` gains exactly one
       squash commit whose tree matches the final branch and holds `vX.Y.Z`.
4. [ ] Test rulesets by attempting direct `main` and `develop` pushes, UI merge
       and rebase merges, force pushes, tag changes, non-release `main` PRs,
       unselected candidate cherry-picks, unsigned tags, and unauthorised sync
       pushes. Each prohibited action must fail.
5. [ ] Test the synchronisation merge with feature commits arriving after the
       RC cut and an open PR based before the merge. Confirm release content
       reaches `develop` with no forced update.
6. [ ] Build the source release twice in fresh isolated environments using only
       locked sources. Verify archive checksums, manifests, SBOM, NOTICE and
       licences, documentation deployment, and public release assets.

## Remaining Decisions {#release-plan-decisions}

- [ ] Choose the first public SemVer tag, recommended `v0.1.0`.
- [ ] Choose GPG or SSH signing and establish Release Manager membership and
      key rotation.
- [ ] Decide which CPU, CUDA, and HIP jobs are release-blocking versus advisory.
- [ ] Confirm a publicly released Neko version compatible with the first target,
      or approve the immutable mirror process before implementation.

## Repository Surfaces {#release-plan-surfaces}

- `.github/workflows/pr_main.yml`: broken reusable-workflow references and an
  incomplete main gate.
- `.github/workflows/pr_develop.yml`: current full develop PR checks and merge
  queue pattern.
- `.github/workflows/check_compile.yml`: reusable compile matrix and action and
  runner pinning target.
- `.github/workflows/documentation.yml`: release deployment path to repair.
- `.github/actions/setup_*/action.yml`, `scripts/dependencies.sh`, and
  `setup.sh`: future lock consumers that currently contain moving references,
  divergent defaults, or checksum-free downloads.
- `documentation/CMakeLists.txt`: documentation dependency fetches to lock.
- `CMakeLists.txt`: authoritative project version and source-package
  configuration.

## Scope Boundaries {#release-plan-scope}

- This plan makes no upstream Neko release-policy changes.
- The first release does not include platform-specific binary distributions or
  a blanket binary ABI guarantee.
- `develop` is never force-updated or rebased. The normal signed
  `main` to `develop` merge after each release is the only non-squash update.
