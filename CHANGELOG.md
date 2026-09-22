# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

<!-- insertion marker -->

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
