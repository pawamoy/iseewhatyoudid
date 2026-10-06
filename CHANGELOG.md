# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

<!-- insertion marker -->
## [0.1.0](https://github.com/pawamoy/iseewhatyoudid/releases/tag/0.1.0) - 2026-10-06

<small>[Compare with first commit](https://github.com/pawamoy/iseewhatyoudid/compare/f9a5664bcecb539cc2f3278626f2120c3a64e3c4...0.1.0)</small>

### Build

- Drop support for Python 3.10 ([6e2997e](https://github.com/pawamoy/iseewhatyoudid/commit/6e2997e46d9a53bcd6382eee418ee2c25108f433) by Timothée Mazzucotelli).

### Features

- Initial implementation ([f9a5664](https://github.com/pawamoy/iseewhatyoudid/commit/f9a5664bcecb539cc2f3278626f2120c3a64e3c4) by Timothée Mazzucotelli).


## Unreleased

### Added

- Add repeatable `--repos-dir` and `--commit-author-email` options to analyze
  extensive public default-branch commit history from local clones.
- Disclose full-clone local, shallow local, and bounded GitHub commit-summary
  sources in the HTML dashboard.

### Changed

- Prefer incrementally cached local Git history over GitHub commit-summary
  requests for matched, confirmed-public repositories.
- Limit local history to the newest 2,000 matching commits per repository.
- Discover all scoped GitHub clones instead of restricting local history to
  repositories present in GitHub's contribution groups.
- Continue clone discovery below a selected directory that is itself a Git
  repository, and report progress while inspecting local remotes.
- Restrict local clone mapping to `origin`, ignoring contributor and pull-request
  remotes.
- Remove the commit-scope chart and exclude merge commits with default subjects
  from commit-summary analysis.
