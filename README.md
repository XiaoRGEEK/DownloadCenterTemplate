# XiaoR Download Center

This repository is the control plane for XiaoR software and firmware releases.
The public release binaries live in Volcengine TOS and are downloaded through
its certificate-valid HTTPS endpoint; regular Git contains only the website,
release metadata, documentation, and validation/deployment automation.

## Release workflow

1. Upload a versioned binary directly to TOS. Never overwrite an existing
   versioned object.
2. Update `data.json`, `update/software.yaml`, or the relevant small updater
   manifest.
3. Run `python3 scripts/validate_release.py`.
4. Push a branch with the `ray-yi-cn` account and open a pull request.
5. `XiaoRGEEK` reviews and merges the pull request.
6. The protected `master` workflow verifies every referenced TOS object, then
   uploads only changed allowlisted metadata/site files. It never deletes TOS
   objects and never performs a recursive upload.

## Retention

- Keep the current release and one rollback release for each supported platform
  or architecture.
- TOS object deletion is a separate, explicitly reviewed maintenance operation.
- Historical TOS object versions expire through the bucket lifecycle policy.

## Website

[GitHub Pages](https://xiaorgeek.github.io/DownloadCenterTemplate/) reads
`data.json`; all software and firmware download buttons resolve to TOS.
