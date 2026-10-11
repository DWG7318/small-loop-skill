package nativeprobe

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"testing"
)

func TestWriteFailureRetainsLastValidSnapshot(t *testing.T) {
	root := t.TempDir()
	if err := Merge(root, "dsh", Host{ID: "original", Coverage: "COMPLETE"}); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(root, "dsh")
	old, _ := os.ReadFile(filepath.Join(dir, "snapshot.json"))
	// A nonempty directory at the one owned temp name makes replacement fail.
	os.Mkdir(filepath.Join(dir, "snapshot.tmp"), 0700)
	os.WriteFile(filepath.Join(dir, "snapshot.tmp", "obstacle"), []byte("owned-test"), 0600)
	if err := Merge(root, "dsh", Host{ID: "new"}); err == nil {
		t.Fatal("write failure hidden")
	}
	after, _ := os.ReadFile(filepath.Join(dir, "snapshot.json"))
	if string(old) != string(after) {
		t.Fatal("old valid evidence lost")
	}
}

func TestNativeCrossProcessMerge(t *testing.T) {
	if root := os.Getenv("SLK_PROBE_TEST_CHILD_ROOT"); root != "" {
		id := os.Getenv("SLK_PROBE_TEST_CHILD_ID")
		for i := 0; i < 30; i++ {
			if err := Merge(root, "dsh", Host{ID: id, Coverage: "COMPLETE", Total: 1, Objects: []Object{{SessionID: id, Status: strconv.Itoa(i)}}}); err != nil {
				t.Fatal(err)
			}
		}
		return
	}
	root := t.TempDir()
	var wg sync.WaitGroup
	var mu sync.Mutex
	failures := []string{}
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			cmd := exec.Command(os.Args[0], "-test.run=^TestNativeCrossProcessMerge$")
			cmd.Env = append(os.Environ(), "SLK_PROBE_TEST_CHILD_ROOT="+root, "SLK_PROBE_TEST_CHILD_ID="+id)
			output, err := cmd.CombinedOutput()
			if err != nil {
				mu.Lock()
				failures = append(failures, string(output))
				mu.Unlock()
			}
		}(strconv.Itoa(i))
	}
	wg.Wait()
	if len(failures) > 0 {
		t.Fatal(failures)
	}
	s, err := Read(root, "dsh")
	if err != nil {
		t.Fatal(err)
	}
	if len(s.Hosts) != 4 {
		t.Fatalf("lost cross-process hosts: %+v", s)
	}
	for _, h := range s.Hosts {
		if h.Objects[0].Status != "29" {
			t.Fatal("last update lost")
		}
	}
}

func TestCorruptNativeRecordRemainsUnknownOnUnchangedNextSample(t *testing.T) {
	root := t.TempDir()
	os.Mkdir(filepath.Join(root, "repo"), 0700)
	os.WriteFile(filepath.Join(root, "repo", "a.jsonl"), []byte("broken\n"), 0600)
	c := NewOCRVCollector(root)
	for i := 0; i < 2; i++ {
		objects, coverage, _ := c.Sample()
		if coverage != "UNKNOWN" || objects[0].Error == "" {
			t.Fatal("unchanged corruption forgotten")
		}
	}
}

func TestMissingProbeIsNotCompleteEmpty(t *testing.T) {
	if _, err := Read(t.TempDir(), "ocrv"); err == nil {
		t.Fatal("unsampled tool pretended empty complete")
	}
}

func TestCrashedWriterOwnedTempAndMutexDoNotBlockNextHost(t *testing.T) {
	if root := os.Getenv("SLK_PROBE_CRASH_CHILD_ROOT"); root != "" {
		dir := filepath.Join(root, "dsh")
		os.MkdirAll(dir, 0700)
		_, err := lockDirectory(dir)
		if err != nil {
			os.Exit(24)
		}
		os.WriteFile(filepath.Join(dir, "snapshot.tmp"), []byte("incomplete owned replacement"), 0600)
		os.Exit(23)
	}
	root := t.TempDir()
	if err := Merge(root, "dsh", Host{ID: "before", Coverage: "COMPLETE"}); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestCrashedWriterOwnedTempAndMutexDoNotBlockNextHost$")
	cmd.Env = append(os.Environ(), "SLK_PROBE_CRASH_CHILD_ROOT="+root)
	if err := cmd.Run(); err == nil {
		t.Fatal("crash fixture did not crash")
	}
	if err := Merge(root, "dsh", Host{ID: "after", Coverage: "COMPLETE"}); err != nil {
		t.Fatal(err)
	}
	s, err := Read(root, "dsh")
	if err != nil || len(s.Hosts) != 2 {
		t.Fatal("valid snapshot lost on crash", err)
	}
	if _, err = os.Stat(filepath.Join(root, "dsh", "snapshot.tmp")); !os.IsNotExist(err) {
		t.Fatal("owned stale replacement not cleared")
	}
}
