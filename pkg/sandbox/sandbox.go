// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

// Package sandbox provides filesystem path validation to prevent directory-
// traversal attacks and restrict file operations to the agent workspace.
package sandbox

import (
	"fmt"
	"os"
	"path/filepath"
)

// ValidatePath resolves requestedPath relative to workspace and returns the
// clean absolute path. It returns an error if:
//   - the resolved path escapes workspace (via "../", absolute paths, or symlinks)
//   - workspace is empty
func ValidatePath(workspace, requestedPath string) (string, error) {
	if workspace == "" {
		return "", fmt.Errorf("sandbox: workspace is required")
	}

	absWorkspace, err := filepath.Abs(workspace)
	if err != nil {
		return "", fmt.Errorf("sandbox: resolve workspace: %w", err)
	}

	var absPath string
	if filepath.IsAbs(requestedPath) {
		absPath = filepath.Clean(requestedPath)
	} else {
		absPath = filepath.Clean(filepath.Join(absWorkspace, requestedPath))
	}

	if !IsWithinWorkspace(absWorkspace, absPath) {
		return "", fmt.Errorf("sandbox: path escapes workspace: %q", requestedPath)
	}

	// Resolve symlinks to prevent symlink-based traversal.
	workspaceReal := absWorkspace
	if resolved, err := filepath.EvalSymlinks(absWorkspace); err == nil {
		workspaceReal = resolved
	}

	if resolved, err := filepath.EvalSymlinks(absPath); err == nil {
		if !IsWithinWorkspace(workspaceReal, resolved) {
			return "", fmt.Errorf("sandbox: symlink resolves outside workspace: %q", requestedPath)
		}
		return resolved, nil
	} else if !os.IsNotExist(err) {
		return "", fmt.Errorf("sandbox: resolve path: %w", err)
	}

	// Path does not exist yet — check the closest existing ancestor.
	if ancestor, err := resolveExistingAncestor(filepath.Dir(absPath)); err == nil {
		if !IsWithinWorkspace(workspaceReal, ancestor) {
			return "", fmt.Errorf("sandbox: symlink resolves outside workspace: %q", requestedPath)
		}
	}

	return absPath, nil
}

// IsWithinWorkspace returns true when absPath is equal to workspace or is a
// descendant of it. Both paths should already be absolute and clean.
func IsWithinWorkspace(workspace, absPath string) bool {
	rel, err := filepath.Rel(filepath.Clean(workspace), filepath.Clean(absPath))
	return err == nil && filepath.IsLocal(rel)
}

// resolveExistingAncestor walks up from path until it finds a directory that
// can be resolved via EvalSymlinks. It returns an error only if the walk
// reaches the filesystem root without success.
func resolveExistingAncestor(path string) (string, error) {
	for current := filepath.Clean(path); ; current = filepath.Dir(current) {
		if resolved, err := filepath.EvalSymlinks(current); err == nil {
			return resolved, nil
		} else if !os.IsNotExist(err) {
			return "", err
		}
		if filepath.Dir(current) == current {
			return "", os.ErrNotExist
		}
	}
}
