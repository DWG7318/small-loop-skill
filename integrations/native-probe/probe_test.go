package nativeprobe

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMergePreservesOtherHostAndQueryIsReadOnly(t *testing.T) {
	root := t.TempDir()
	first := Host{ID: "first", PID: os.Getpid(), ObservedAt: "2026-10-11T01:00:00Z", Coverage: "COMPLETE", Total: 2, Objects: []Object{{SessionID: "stopped", Status: "COMPLETED"}, {SessionID: "running", Status: "RUNNING"}}}
	if err := Merge(root, "dsh", first); err != nil {
		t.Fatal(err)
	}
	if err := Merge(root, "dsh", Host{ID: "second", ObservedAt: "2026-10-11T01:01:00Z", Coverage: "UNKNOWN"}); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "dsh", "snapshot.json")
	before, _ := os.ReadFile(path)
	got, err := Read(root, "dsh")
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Hosts) != 2 || got.Hosts["first"].Objects[0].Status != "COMPLETED" || got.Hosts["first"].Objects[1].Status != "RUNNING" {
		t.Fatalf("lost distinct objects: %+v", got)
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("query mutated evidence")
	}
}

func TestBudgetIncludesTemporaryAndDoesNotPretendComplete(t *testing.T) {
	root := t.TempDir()
	objects := make([]Object, 20000)
	for i := range objects {
		objects[i] = Object{SessionID: strings.Repeat("s", 200), Source: strings.Repeat("p", 500), Status: "UNKNOWN"}
	}
	if err := Merge(root, "ocrv", Host{ID: "host", Coverage: "COMPLETE", Total: len(objects), Objects: objects}); err != nil {
		t.Fatal(err)
	}
	got, err := Read(root, "ocrv")
	if err != nil {
		t.Fatal(err)
	}
	if got.Coverage != "UNKNOWN" || got.Hosts["host"].Omitted == 0 || got.Hosts["host"].Total != len(objects) {
		t.Fatal("capacity loss was concealed")
	}
	info, _ := os.Stat(filepath.Join(root, "ocrv", "snapshot.json"))
	if info.Size()*2 > BudgetBytes {
		t.Fatal("replacement exceeds shared budget")
	}
	entries, _ := os.ReadDir(filepath.Join(root, "ocrv"))
	var size int64
	for _, e := range entries {
		s, _ := e.Info()
		size += s.Size()
	}
	if size > BudgetBytes {
		t.Fatal("tool exceeds total budget")
	}
}

func TestCorruptStoreNeverSilentlyReplacesOtherHosts(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "dsh")
	os.MkdirAll(dir, 0700)
	path := filepath.Join(dir, "snapshot.json")
	os.WriteFile(path, []byte("broken"), 0600)
	err := Merge(root, "dsh", Host{ID: "new"})
	if err == nil {
		t.Fatal("corruption silently accepted")
	}
	data, _ := os.ReadFile(path)
	if string(data) != "broken" {
		t.Fatal("corrupt original overwritten")
	}
}

func TestOCRVFullRecordOverTenMiBAndPartialTail(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "repo", "native.jsonl")
	os.MkdirAll(filepath.Dir(path), 0700)
	payload := `{"type":"llm_response","timestamp":"2026-10-11T01:00:00Z","content":"` + strings.Repeat("x", 11*1024*1024) + "\"}\n" + `{"type":"session_end"}`
	os.WriteFile(path, []byte(payload), 0600)
	collector := NewOCRVCollector(root)
	objects, coverage, err := collector.Sample()
	if err != nil {
		t.Fatal(err)
	}
	if coverage != "COMPLETE" || len(objects) != 1 || objects[0].EventType != "llm_response" || objects[0].Status == "COMPLETED" {
		t.Fatalf("bad full/partial parse: %+v %s", objects, coverage)
	}
	file, _ := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0600)
	file.WriteString("\n")
	file.Close()
	objects, _, err = collector.Sample()
	if err != nil || objects[0].Status != "CLOSED" {
		t.Fatalf("end not observed: %+v %v", objects, err)
	}
	data, _ := json.Marshal(objects)
	if strings.Contains(string(data), strings.Repeat("x", 100)) {
		t.Fatal("body leaked")
	}
	if objects[0].CompleteBytes != int64(len(payload)+1) {
		t.Fatal("incremental complete offset wrong")
	}
}

func TestOCRVReplacementAndFailureAreNotFalseRunning(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "repo", "same.jsonl")
	os.MkdirAll(filepath.Dir(path), 0700)
	os.WriteFile(path, []byte("{\"type\":\"session_end\"}\n"), 0600)
	c := NewOCRVCollector(root)
	first, _, _ := c.Sample()
	if first[0].Status != "CLOSED" {
		t.Fatal("end")
	}
	os.Remove(path)
	os.WriteFile(path, []byte("{\"type\":\"session_start\"}\n"), 0600)
	second, _, err := c.Sample()
	if err != nil || second[0].Status != "UNKNOWN" {
		t.Fatal("replacement retained terminal status")
	}
	os.WriteFile(path, []byte("not-json\n"), 0600)
	third, coverage, _ := c.Sample()
	if coverage != "UNKNOWN" || third[0].Status != "UNKNOWN" {
		t.Fatal("bad record concealed")
	}
}

func TestCurrentProcessIdentityIsOSBacked(t *testing.T) {
	one, err := ProcessIdentity(os.Getpid())
	if err != nil || one == "" {
		t.Fatalf("OS identity: %s %v", one, err)
	}
	time.Sleep(time.Millisecond)
	two, _ := ProcessIdentity(os.Getpid())
	if one != two {
		t.Fatal("identity was sampling time")
	}
}

func TestOCRVCursorDoesNotInheritAnotherHostOwnership(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "repo", "native.jsonl")
	os.MkdirAll(filepath.Dir(path), 0700)
	os.WriteFile(path, []byte("{\"type\":\"session_start\"}\n"), 0600)
	first, _, _ := NewOCRVCollector(root).Sample()
	first[0].OwnerBound = true
	second := NewOCRVCollector(root)
	second.Seed(Snapshot{Hosts: map[string]Host{"old-host": {Objects: first}}})
	objects, _, err := second.Sample()
	if err != nil || objects[0].OwnerBound {
		t.Fatal("cursor inherited another native process's writer ownership", err)
	}
}

func TestOCRVSessionEndIsNotAutomaticallySuccessful(t *testing.T) {
	for _, item := range []struct{ manifest, want string }{
		{"", "CLOSED"},
		{`,"run_manifest":{"schema_version":"ocr.run-manifest/v1","terminal_state":"complete"}`, "COMPLETED"},
		{`,"run_manifest":{"schema_version":"ocr.run-manifest/v1","terminal_state":"failed"}`, "FAILED"},
		{`,"run_manifest":{"schema_version":"ocr.run-manifest/v1","terminal_state":"partial"}`, "PARTIAL"},
		{`,"run_manifest":{"schema_version":"ocr.run-manifest/v1","terminal_state":"skipped"}`, "SKIPPED"},
		{`,"run_manifest":{"schema_version":"ocr.run-manifest/v999","terminal_state":"complete"}`, "CLOSED"},
	} {
		t.Run(item.want+item.manifest, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, "repo", "native.jsonl")
			os.MkdirAll(filepath.Dir(path), 0700)
			os.WriteFile(path, []byte(`{"type":"session_end"`+item.manifest+"}\n"), 0600)
			objects, _, err := NewOCRVCollector(root).Sample()
			if err != nil || objects[0].Status != item.want {
				t.Fatalf("native closure != success: %+v %v", objects, err)
			}
		})
	}
}
