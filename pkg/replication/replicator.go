package replication

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/GemachDAO/Gclaw/pkg/config"
)

// ReplicationConfig holds settings for the agent self-replication feature.
type ReplicationConfig struct {
	Enabled           bool    `json:"enabled"`
	MaxChildren       int     `json:"max_children"`        // max child agents (default 3)
	GMACSharePercent  float64 `json:"gmac_share_percent"`  // % of parent GMAC given to child (default 50)
	MutatePrompt      bool    `json:"mutate_prompt"`       // allow prompt mutation in children (default true)
	InheritSkills     bool    `json:"inherit_skills"`      // copy parent skills to child (default true)
	InheritMemory     bool    `json:"inherit_memory"`      // copy parent memory to child (default true)
	ChildWorkspaceDir string  `json:"child_workspace_dir"` // base dir for child workspaces
}

// ChildAgent represents a replicated child agent instance.
type ChildAgent struct {
	ID            string   `json:"id"`
	ParentID      string   `json:"parent_id"`
	Generation    int      `json:"generation"`
	WorkspacePath string   `json:"workspace_path"`
	ConfigPath    string   `json:"config_path"`
	CreatedAt     int64    `json:"created_at"`
	GMACBalance   float64  `json:"initial_gmac"`
	Status        string   `json:"status"`
	Mutations     []string `json:"mutations"`
}

// Replicator handles spawning persistent child Gclaw agents
// that inherit config, skills, and memory from the parent.
type Replicator struct {
	config   ReplicationConfig
	children []*ChildAgent
	parentID string
	mu       sync.RWMutex
}

// NewReplicator creates a new Replicator for the given parent agent.
func NewReplicator(parentID string, cfg ReplicationConfig) *Replicator {
	if cfg.MaxChildren == 0 {
		cfg.MaxChildren = 3
	}
	if cfg.GMACSharePercent == 0 {
		cfg.GMACSharePercent = 50
	}
	return &Replicator{
		config:   cfg,
		children: []*ChildAgent{},
		parentID: parentID,
	}
}

// CanReplicate returns true if goodwill meets or exceeds the replication threshold.
func (r *Replicator) CanReplicate(goodwill int, threshold int) bool {
	return goodwill >= threshold
}

// GoodwillSource is an optional interface for retrieving the current goodwill score.
// This allows the tools layer to pass metabolism without importing it directly.
type GoodwillSource interface {
	GetGoodwill() int
}

// Replicate creates a new child agent, copying config, skills, and memory
// from the parent. It returns the ChildAgent descriptor or an error.
// parentGMAC is passed by pointer so the share can be deducted in-place.
func (r *Replicator) Replicate(parentConfig *config.Config, parentWorkspace string, parentGMAC *float64) (*ChildAgent, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if !r.config.Enabled {
		return nil, fmt.Errorf("replication is disabled")
	}
	if len(r.children) >= r.config.MaxChildren {
		return nil, fmt.Errorf("max children (%d) already reached", r.config.MaxChildren)
	}

	ts := time.Now()
	childID := fmt.Sprintf("gclaw-child-%d", ts.UnixMilli())

	baseDir := r.config.ChildWorkspaceDir
	if baseDir == "" {
		baseDir = filepath.Join(parentWorkspace, "children")
	}
	childWorkspace := filepath.Join(baseDir, childID)
	if err := os.MkdirAll(childWorkspace, 0o755); err != nil {
		return nil, fmt.Errorf("create child workspace: %w", err)
	}

	// Deep-copy parent config via JSON round-trip
	childCfg, err := deepCopyConfig(parentConfig)
	if err != nil {
		return nil, fmt.Errorf("copy config: %w", err)
	}

	// Set child workspace
	childCfg.Agents.Defaults.Workspace = childWorkspace

	// Assign a unique gateway port (parent port + child index)
	childCfg.Gateway.Port = parentConfig.Gateway.Port + len(r.children) + 1

	var mutations []string

	// Mutate system prompt if enabled — write mutation to child workspace
	// so the agent loop picks it up via LoadBootstrapFiles.
	if r.config.MutatePrompt {
		mutation := mutateSystemPrompt("")
		mutations = append(mutations, mutation)
		strategyPath := filepath.Join(childWorkspace, "TRADING_STRATEGY.md")
		_ = os.WriteFile(strategyPath, []byte("## Trading Strategy\n\n"+mutation+"\n"), 0o600)
	}

	// Copy skills directory
	if r.config.InheritSkills {
		src := filepath.Join(parentWorkspace, "skills")
		dst := filepath.Join(childWorkspace, "skills")
		_ = copyDir(src, dst)
	}

	// Copy memory directory
	if r.config.InheritMemory {
		src := filepath.Join(parentWorkspace, "memory")
		dst := filepath.Join(childWorkspace, "memory")
		_ = copyDir(src, dst)
	}

	// Split GMAC balance
	share := *parentGMAC * (r.config.GMACSharePercent / 100.0)
	*parentGMAC -= share

	// Save child config
	childConfigPath := filepath.Join(childWorkspace, "config.json")
	if err := config.SaveConfig(childConfigPath, childCfg); err != nil {
		return nil, fmt.Errorf("save child config: %w", err)
	}

	child := &ChildAgent{
		ID:            childID,
		ParentID:      r.parentID,
		Generation:    1,
		WorkspacePath: childWorkspace,
		ConfigPath:    childConfigPath,
		CreatedAt:     ts.UnixMilli(),
		GMACBalance:   share,
		Status:        "running",
		Mutations:     mutations,
	}

	r.children = append(r.children, child)
	return child, nil
}

// ListChildren returns a snapshot of all child agents.
func (r *Replicator) ListChildren() []*ChildAgent {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]*ChildAgent, len(r.children))
	copy(out, r.children)
	return out
}

// GetChild returns the child agent with the given ID, or false if not found.
func (r *Replicator) GetChild(id string) (*ChildAgent, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, c := range r.children {
		if c.ID == id {
			return c, true
		}
	}
	return nil, false
}

// StopChild marks a child agent as stopped.
func (r *Replicator) StopChild(id string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, c := range r.children {
		if c.ID == id {
			c.Status = "stopped"
			return nil
		}
	}
	return fmt.Errorf("child %q not found", id)
}

// deepCopyConfig performs a deep copy of the config via JSON marshaling.
func deepCopyConfig(src *config.Config) (*config.Config, error) {
	data, err := json.Marshal(src)
	if err != nil {
		return nil, err
	}
	var dst config.Config
	if err := json.Unmarshal(data, &dst); err != nil {
		return nil, err
	}
	return &dst, nil
}

// copyDir recursively copies src directory to dst. Errors are silently ignored
// for missing source directories (inheriting nothing is valid).
func copyDir(src, dst string) error {
	info, err := os.Stat(src)
	if err != nil {
		return nil // source does not exist, skip
	}
	if !info.IsDir() {
		return nil
	}
	if err := os.MkdirAll(dst, 0o755); err != nil {
		return err
	}
	entries, err := os.ReadDir(src)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		srcPath := filepath.Join(src, entry.Name())
		dstPath := filepath.Join(dst, entry.Name())
		if entry.IsDir() {
			if err := copyDir(srcPath, dstPath); err != nil {
				return err
			}
		} else {
			if err := copyFile(srcPath, dstPath); err != nil {
				return err
			}
		}
	}
	return nil
}

// copyFile copies a single file from src to dst.
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, in)
	return err
}
