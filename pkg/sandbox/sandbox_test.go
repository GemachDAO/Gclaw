// Gclaw - Ultra-lightweight personal AI agent
// License: MIT
//
// Copyright (c) 2026 Gclaw contributors

package sandbox

import (
	"os"
	"path/filepath"
	"testing"
)

func TestValidatePath_ValidRelative(t *testing.T) {
	dir := t.TempDir()
	got, err := ValidatePath(dir, "subdir/file.txt")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join(dir, "subdir", "file.txt")
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestValidatePath_TraversalBlocked(t *testing.T) {
	dir := t.TempDir()
	_, err := ValidatePath(dir, "../../../etc/passwd")
	if err == nil {
		t.Fatal("expected error for traversal, got nil")
	}
}

func TestValidatePath_AbsoluteOutsideBlocked(t *testing.T) {
	dir := t.TempDir()
	_, err := ValidatePath(dir, "/etc/passwd")
	if err == nil {
		t.Fatal("expected error for absolute path outside workspace")
	}
}

func TestValidatePath_WorkspaceRootAllowed(t *testing.T) {
	dir := t.TempDir()
	got, err := ValidatePath(dir, ".")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got == "" {
		t.Error("expected non-empty path for workspace root")
	}
}

func TestValidatePath_EmptyWorkspace(t *testing.T) {
	_, err := ValidatePath("", "foo.txt")
	if err == nil {
		t.Fatal("expected error for empty workspace")
	}
}

func TestValidatePath_PathWithinWorkspaceAllowed(t *testing.T) {
	dir := t.TempDir()
	// Create a real file inside workspace
	subDir := filepath.Join(dir, "data")
	if err := os.MkdirAll(subDir, 0o755); err != nil {
		t.Fatal(err)
	}
	filePath := filepath.Join(subDir, "test.txt")
	if err := os.WriteFile(filePath, []byte("hello"), 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := ValidatePath(dir, "data/test.txt")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != filePath {
		t.Errorf("got %q, want %q", got, filePath)
	}
}

func TestValidatePath_SymlinkOutsideBlocked(t *testing.T) {
	dir := t.TempDir()
	outside := t.TempDir()

	// Create a symlink inside workspace pointing outside
	link := filepath.Join(dir, "escape")
	if err := os.Symlink(outside, link); err != nil {
		t.Skip("symlinks not supported:", err)
	}

	_, err := ValidatePath(dir, "escape")
	if err == nil {
		t.Fatal("expected error for symlink escaping workspace")
	}
}

func TestIsWithinWorkspace_True(t *testing.T) {
	dir := t.TempDir()
	sub := filepath.Join(dir, "a", "b")
	if !IsWithinWorkspace(dir, sub) {
		t.Errorf("expected %q to be within %q", sub, dir)
	}
}

func TestIsWithinWorkspace_False(t *testing.T) {
	dir := t.TempDir()
	other := t.TempDir()
	if IsWithinWorkspace(dir, other) {
		t.Errorf("expected %q NOT to be within %q", other, dir)
	}
}
