package replication

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// WriteMessage writes a TelepathyMessage as a JSON file into the telepathy
// directory for the given family. Files are named {timestamp}-{from_agent_id}.json.
func WriteMessage(dir string, msg TelepathyMessage) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create telepathy dir: %w", err)
	}

	if msg.Timestamp == 0 {
		msg.Timestamp = time.Now().UnixMilli()
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}

	name := fmt.Sprintf("%d-%s.json", msg.Timestamp, sanitizeID(msg.FromAgentID))
	path := filepath.Join(dir, name)
	return os.WriteFile(path, data, 0o600)
}

// StartFileWatcher polls the given directory for new JSON message files and
// calls callback for each new message. It stops when done is closed.
// pollInterval controls the check frequency; if zero, defaults to 2 seconds.
// msgMaxAge controls when old message files are deleted; if zero, defaults to 1 hour.
func StartFileWatcher(
	dir string,
	pollInterval time.Duration,
	msgMaxAge time.Duration,
	callback func(TelepathyMessage),
	done <-chan struct{},
) {
	if pollInterval <= 0 {
		pollInterval = 2 * time.Second
	}
	if msgMaxAge <= 0 {
		msgMaxAge = time.Hour
	}

	seen := make(map[string]struct{})

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			cleanOldMessages(dir, msgMaxAge)
			entries, err := os.ReadDir(dir)
			if err != nil {
				continue
			}
			for _, entry := range entries {
				if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
					continue
				}
				if _, ok := seen[entry.Name()]; ok {
					continue
				}
				seen[entry.Name()] = struct{}{}
				path := filepath.Join(dir, entry.Name())
				data, err := os.ReadFile(path)
				if err != nil {
					continue
				}
				var msg TelepathyMessage
				if err := json.Unmarshal(data, &msg); err != nil {
					continue
				}
				callback(msg)
			}
		}
	}
}

// TelepathyDir returns the standard telepathy directory for a family within a workspace.
func TelepathyDir(workspace, familyID string) string {
	return filepath.Join(workspace, "replication", "telepathy", familyID)
}

// cleanOldMessages removes message files older than maxAge from the directory.
func cleanOldMessages(dir string, maxAge time.Duration) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	cutoff := time.Now().Add(-maxAge)
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		if info.ModTime().Before(cutoff) {
			_ = os.Remove(filepath.Join(dir, entry.Name()))
		}
	}
}

// sanitizeID replaces characters that are invalid in filenames with underscores.
func sanitizeID(id string) string {
	var b strings.Builder
	for _, r := range id {
		if r == '/' || r == '\\' || r == ':' || r == '*' || r == '?' || r == '"' || r == '<' || r == '>' || r == '|' {
			b.WriteRune('_')
		} else {
			b.WriteRune(r)
		}
	}
	return b.String()
}
