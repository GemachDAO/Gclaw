package replication

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// SaveChildren persists the current children list to
// {workspace}/replication/children.json using an atomic write.
func (r *Replicator) SaveChildren(workspace string) error {
	r.mu.RLock()
	data, err := json.MarshalIndent(r.children, "", "  ")
	r.mu.RUnlock()
	if err != nil {
		return err
	}

	dir := filepath.Join(workspace, "replication")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	path := filepath.Join(dir, "children.json")
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// LoadChildren restores the children list from
// {workspace}/replication/children.json. Missing file is treated as empty.
func (r *Replicator) LoadChildren(workspace string) error {
	path := filepath.Join(workspace, "replication", "children.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}

	var children []*ChildAgent
	if err := json.Unmarshal(data, &children); err != nil {
		return err
	}

	r.mu.Lock()
	r.children = children
	r.mu.Unlock()
	return nil
}
