# Independent data clones with one production checkout

Work claim: `repo-4`, 2026-09-12.

- DC-1 (opt-in independent clone preparation and migration): attempted.
- DC-2 (production publication source and ownership guards): attempted.
- DC-3 (temporary-repository regression tests and full quota-free suite): attempted.
- DC-4 (safe migration of repo-4 and preservation of its experiment): attempted.

The operator authorized independent private data branches and commits for
experiment owners. The shared live checkout remains under repo-0 ownership.
This migration must not pull, reset, stage or commit that shared checkout,
change another clone, disturb running jobs, spend model quota or deploy.

Public baseline: `98a7de6239a36a6e3f1034b9d63f89d85098f91b`.
Private baseline: `06f1ec2a1b41aeed5cec0d1c4f0ae85cd180c399`.
Full setup, integration and publication instructions will replace this claim
when the tooling and tests pass.
