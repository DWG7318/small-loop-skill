// Package nativeprobe records native metadata, never engineering decisions.
package nativeprobe

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

const Version = "1.0.0"
const BudgetBytes int64 = 10 * 1024 * 1024
const Interval = 60 * time.Second

type Object struct {
	SessionID        string `json:"session_id"`
	Source           string `json:"source,omitempty"`
	SourceIdentity   string `json:"source_identity,omitempty"`
	SourceBytes      int64  `json:"source_bytes,omitempty"`
	SourceModifiedAt string `json:"source_modified_at,omitempty"`
	CompleteBytes    int64  `json:"complete_bytes,omitempty"`
	EventType        string `json:"event_type,omitempty"`
	EventAt          string `json:"event_at,omitempty"`
	EventSHA256      string `json:"event_sha256,omitempty"`
	EventSource      string `json:"event_source,omitempty"`
	EventCount       int64  `json:"event_count,omitempty"`
	Status           string `json:"status"`
	Live             bool   `json:"live,omitempty"`
	Persisted        bool   `json:"persisted,omitempty"`
	OwnerBound       bool   `json:"owner_bound,omitempty"`
	NativeRevision   string `json:"native_revision,omitempty"`
	Error            string `json:"error,omitempty"`
}

type Host struct {
	ID             string   `json:"id"`
	PID            int      `json:"pid"`
	ProcessCreated string   `json:"process_created"`
	Device         string   `json:"device"`
	NativeHome     string   `json:"native_home"`
	ObservedAt     string   `json:"observed_at"`
	RecordedAt     string   `json:"recorded_at,omitempty"`
	LifecycleAt    string   `json:"lifecycle_at,omitempty"`
	Lifecycle      string   `json:"lifecycle"`
	Coverage       string   `json:"coverage"`
	Total          int      `json:"total"`
	Archived       int      `json:"archived"`
	ArchiveSource  string   `json:"archive_source,omitempty"`
	Omitted        int      `json:"omitted"`
	Objects        []Object `json:"objects"`
	Error          string   `json:"error,omitempty"`
	// Liveness is populated at query time, not persisted as a fresh sample.
	Liveness string `json:"liveness,omitempty"`
}

type Snapshot struct {
	Schema   string          `json:"schema"`
	Tool     string          `json:"tool"`
	Version  string          `json:"version"`
	Coverage string          `json:"coverage"`
	Hosts    map[string]Host `json:"hosts"`
}

func DefaultRoot() string {
	if local := os.Getenv("LOCALAPPDATA"); local != "" {
		return filepath.Join(local, "SLK", "native-probe")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".local", "state", "slk", "native-probe")
}

func NewHost(tool, home string, pid int) (Host, error) {
	identity, err := ProcessIdentity(pid)
	if err != nil {
		return Host{}, err
	}
	device, err := os.Hostname()
	if err != nil {
		return Host{}, err
	}
	abs, err := filepath.Abs(home)
	if err != nil {
		return Host{}, err
	}
	key := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%s\x00%d\x00%s", tool, abs, device, pid, identity)))
	return Host{ID: hex.EncodeToString(key[:]), PID: pid, ProcessCreated: identity, Device: device, NativeHome: abs, Objects: []Object{}}, nil
}

func toolPath(root, tool string) (string, error) {
	if tool != "dsh" && tool != "ocrv" {
		return "", errors.New("tool must be dsh or ocrv")
	}
	if root == "" {
		return "", errors.New("probe storage root is unavailable")
	}
	return filepath.Join(root, tool), nil
}
