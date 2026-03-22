package utils

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
)

type configWorkspace struct {
	Agents struct {
		Defaults struct {
			Workspace string `json:"workspace"`
		} `json:"defaults"`
	} `json:"agents"`
}

func ResolveWorkspaceSkillDir(envVar, skillSubdir string) string {
	if dir := strings.TrimSpace(os.Getenv(envVar)); dir != "" {
		return dir
	}

	normalizedSubdir := filepath.FromSlash(skillSubdir)
	workspaceCandidate := ""
	if workspace := configuredWorkspaceDir(); workspace != "" {
		workspaceCandidate = filepath.Join(workspace, "skills", normalizedSubdir)
	}
	cwdCandidate := ""
	if wd, err := os.Getwd(); err == nil {
		cwdCandidate = filepath.Join(wd, "workspace", "skills", normalizedSubdir)
	}

	candidates := []string{workspaceCandidate}
	if exePath, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exePath)
		candidates = append(candidates,
			filepath.Join(exeDir, "workspace", "skills", normalizedSubdir),
			filepath.Join(exeDir, "..", "workspace", "skills", normalizedSubdir),
		)
	}
	candidates = append(candidates, cwdCandidate)

	for _, candidate := range uniqueStrings(candidates) {
		if dirExists(candidate) {
			return candidate
		}
	}

	if workspaceCandidate != "" {
		return workspaceCandidate
	}
	if cwdCandidate != "" {
		return cwdCandidate
	}
	return filepath.Join("workspace", "skills", normalizedSubdir)
}

func configuredWorkspaceDir() string {
	if workspace := strings.TrimSpace(os.Getenv("GCLAW_WORKSPACE")); workspace != "" {
		return expandHomePath(workspace)
	}

	cfgPath := filepath.Join(defaultGclawHome(), "config.json")
	data, err := os.ReadFile(cfgPath)
	if err != nil {
		return filepath.Join(defaultGclawHome(), "workspace")
	}

	var cfg configWorkspace
	if err := json.Unmarshal(data, &cfg); err != nil {
		return filepath.Join(defaultGclawHome(), "workspace")
	}

	if workspace := strings.TrimSpace(cfg.Agents.Defaults.Workspace); workspace != "" {
		return expandHomePath(workspace)
	}
	return filepath.Join(defaultGclawHome(), "workspace")
}

func defaultGclawHome() string {
	if home := strings.TrimSpace(os.Getenv("GCLAW_HOME")); home != "" {
		return expandHomePath(home)
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ".gclaw"
	}
	return filepath.Join(home, ".gclaw")
}

func expandHomePath(path string) string {
	if path == "" || path[0] != '~' {
		return path
	}

	home, err := os.UserHomeDir()
	if err != nil {
		return path
	}

	switch {
	case path == "~":
		return home
	case strings.HasPrefix(path, "~/"):
		return filepath.Join(home, path[2:])
	default:
		return path
	}
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func uniqueStrings(values []string) []string {
	seen := make(map[string]struct{}, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		if value == "" {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		result = append(result, value)
	}
	return result
}
