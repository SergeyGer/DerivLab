# Versioned Documentation

The README and Wiki describe the **latest `main`**. This directory keeps
immutable release snapshots for support and audits.

| Version | Status | Snapshot | Release notes |
|---|---|---|---|
| `main` | Development | [README](../../README.md) · [Wiki](https://github.com/SergeyGer/DerivLab/wiki) | [Unreleased](../../CHANGELOG.md) |
| **1.2.0** | **Current** | [v1.2.0](v1.2.0.md) | [v1.2.0](../../CHANGELOG.md) |
| 1.1.0 | Superseded | [v1.1.0](v1.1.0.md) | [v1.1.0](../../CHANGELOG.md) |
| 1.0.1 | Legacy | [v1.0.1](v1.0.1.md) | [v1.0.1](../../CHANGELOG.md) |

## Rules

- Snapshot files are immutable after a release.
- The current version snapshot must exist before a release is announced.
- The compatibility matrix is maintained in [COMPATIBILITY.md](../COMPATIBILITY.md).
- The docs validator checks that every snapshot is linked here and that the
  current `APP_VERSION` has a snapshot.
- Wiki pages document `main`; the snapshot is the release-time reference.
