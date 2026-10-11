package nativeprobe

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

func readPath(path, tool string) (Snapshot, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return Snapshot{Schema: "slk.native-probe/v1", Tool: tool, Version: Version, Coverage: "COMPLETE", Hosts: map[string]Host{}}, nil
	}
	if err != nil {
		return Snapshot{}, err
	}
	var s Snapshot
	if err = json.Unmarshal(data, &s); err != nil {
		return s, fmt.Errorf("existing probe snapshot is corrupt: %w", err)
	}
	if s.Schema != "slk.native-probe/v1" || s.Tool != tool || s.Hosts == nil {
		return s, errors.New("existing probe snapshot identity is invalid")
	}
	return s, nil
}

// Merge serializes all hosts in one tool file. Two <=half-budget files are the
// entire owned on-disk data during replacement, including crash leftovers.
func Merge(root, tool string, host Host) error {
	dir, err := toolPath(root, tool)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	unlock, err := lockDirectory(dir)
	if err != nil {
		return err
	}
	defer unlock()
	path := filepath.Join(dir, "snapshot.json")
	temporary := filepath.Join(dir, "snapshot.tmp")
	if err = os.Remove(temporary); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	s, err := readPath(path, tool)
	if err != nil {
		return err
	}
	host.Liveness = ""
	s.Hosts[host.ID] = host
	ids := make([]string, 0, len(s.Hosts))
	for id := range s.Hosts {
		ids = append(ids, id)
	}
	// Retain every host identity and explicit omission count; never substitute
	// another active session for a missing object or claim a partial list complete.
	sort.Slice(ids, func(i, j int) bool { return s.Hosts[ids[i]].ObservedAt < s.Hosts[ids[j]].ObservedAt })
	var data []byte
	for {
		s.Coverage = "COMPLETE"
		for _, h := range s.Hosts {
			if h.Coverage != "COMPLETE" || h.Omitted > 0 {
				s.Coverage = "UNKNOWN"
			}
		}
		data, err = json.Marshal(s)
		if err != nil {
			return err
		}
		if int64(len(data)+1) <= BudgetBytes/2 {
			break
		}
		removed := false
		for _, id := range ids {
			h := s.Hosts[id]
			if len(h.Objects) > 0 {
				cut := len(h.Objects) / 4
				if cut < 1 {
					cut = 1
				}
				h.Objects = h.Objects[:len(h.Objects)-cut]
				h.Omitted += cut
				h.Coverage = "UNKNOWN"
				s.Hosts[id] = h
				removed = true
				break
			}
		}
		if !removed {
			return errors.New("probe host index exceeds budget; previous snapshot retained")
		}
	}
	f, err := os.OpenFile(temporary, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	committed := false
	defer func() {
		f.Close()
		if !committed {
			os.Remove(temporary)
		}
	}()
	if _, err = f.Write(append(data, '\n')); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = replaceFile(temporary, path); err != nil {
		return err
	}
	committed = true
	return nil
}

// Read only reads the existing snapshot and checks OS process identity. It
// neither samples sessions nor writes/renews observed_at.
func Read(root, tool string) (Snapshot, error) {
	dir, err := toolPath(root, tool)
	if err != nil {
		return Snapshot{}, err
	}
	path := filepath.Join(dir, "snapshot.json")
	if _, err := os.Stat(path); err != nil {
		return Snapshot{}, err
	}
	s, err := readPath(path, tool)
	if err != nil {
		return s, err
	}
	for id, h := range s.Hosts {
		identity, e := ProcessIdentity(h.PID)
		h.Liveness = "UNKNOWN"
		if e == nil {
			if identity == h.ProcessCreated && h.ProcessCreated != "" {
				h.Liveness = "ALIVE"
			} else {
				h.Liveness = "EXITED_OR_PID_REUSED"
			}
		} else if errors.Is(e, os.ErrNotExist) {
			h.Liveness = "EXITED"
		}
		s.Hosts[id] = h
	}
	return s, nil
}
