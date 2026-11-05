# Installed Partlet and deployment directories

Partlet users should be able to install a version of the tool without
editing its checkout. The installed Python package must carry the Worker
and the pinned setup inputs needed after that checkout is removed.

## User contract

- Install from a checkout, a pinned Git revision, or a built wheel using
  uv. A checkout installer combines installation and explicit dependency
  setup. uv and Node/npm are external prerequisites, with clear errors
  when absent; installation does not change system runtimes.
- `partlet setup` downloads the checksum-pinned scanner;
  `partlet setup --worker` also installs the lockfile-pinned npm tools.
  Ordinary commands do not install tools implicitly.
- Tools live in Partlet's user-data directory, with `PARTLET_DATA_DIR`
  available for isolation. Worker runtime directories are identified by
  their packaged inputs, including when the package version is
  unchanged. An interrupted install is not considered usable.
- `partlet.toml` remains in the source repository. Each deployment has a
  separate user-owned `wrangler.toml`, created by
  `partlet worker init DIRECTORY`. Reinitializing cannot overwrite it.
- Worker commands require an explicit config path. Partlet supplies the
  installed Worker entry point; user configuration does not depend on a
  checkout or a particular installation path.
- `partlet worker preview` serves previously built output through local
  simulated R2. Preview storage is isolated and disposable. Dry-run
  deployment and preview require no cloud credentials or account access.
- Real deployment identifies the billable target and requests
  confirmation. It does not create buckets. Agents validate local
  behavior and leave real deployment to the user.
- Upgrading replaces installed code and tools while preserving
  deployment configuration, source manifests, approvals and credentials.
  Deploying the upgraded Worker remains a separate action.

## Implementation and validation

The runtime author owns packaged resources, dependency setup and scanner
discovery. The Worker author owns config initialization, CLI commands
and local preview. Their shared API is `asset_root`, `worker_root`,
`managed_gitleaks`, `setup(worker=False)` and `SetupError` in
`partlet.runtime`. The coordinator owns integration and documentation.

Validate failure and retry paths, config preservation, multiple targets,
exit-code handling and refusal of invalid targets. Build and install a
wheel in an isolated environment, run it outside the checkout, prepare
dependencies in isolated user data, and exercise the installed Worker
through local preview and a credential-free deployment dry run. Run the
repository's full checks and get independent review of the combined
change. No release publication or hosted deployment is part of this
work.
