# Meta (Shared Workflow State)

This directory contains persistent data structures used as shared state between GitHub Actions workflows.

## `path-mapping.json`

A key-value index mapping image filenames to their source BagIt paths.

### Usage

This file is:
- written incrementally by ingestion workflows
- read by downstream workflows for file placement and resolution

### Important

This file is a dependency for multiple workflows and must not be deleted or regenerated from scratch.
