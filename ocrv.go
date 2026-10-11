package nativeprobe

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type fileCursor struct {
	info   os.FileInfo
	object Object
}
type OCRVCollector struct {
	Root  string
	cache map[string]fileCursor
}

func NewOCRVCollector(root string) *OCRVCollector {
	return &OCRVCollector{Root: root, cache: map[string]fileCursor{}}
}

// Seed reuses only compact cursors whose physical native file identity still
// matches. No separate disk index is added to the shared budget.
func (c *OCRVCollector) Seed(snapshot Snapshot) {
	for _, host := range snapshot.Hosts {
		for _, object := range host.Objects {
			if object.Source == "" || object.SourceIdentity == "" {
				continue
			}
			old, exists := c.cache[object.Source]
			if !exists || object.CompleteBytes > old.object.CompleteBytes {
				c.cache[object.Source] = fileCursor{object: object}
			}
		}
	}
}

// Sample reads every repository's native JSONL list; complete records are
// incrementally consumed without any body/read cap. Only metadata survives.
func (c *OCRVCollector) Sample() ([]Object, string, error) {
	dirs, err := os.ReadDir(c.Root)
	if errors.Is(err, os.ErrNotExist) {
		return []Object{}, "COMPLETE", nil
	}
	if err != nil {
		return nil, "UNKNOWN", err
	}
	objects := []Object{}
	coverage := "COMPLETE"
	next := map[string]fileCursor{}
	for _, dir := range dirs {
		if !dir.IsDir() {
			continue
		}
		files, e := os.ReadDir(filepath.Join(c.Root, dir.Name()))
		if e != nil {
			coverage = "UNKNOWN"
			continue
		}
		for _, entry := range files {
			if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 || !strings.HasSuffix(entry.Name(), ".jsonl") {
				continue
			}
			path := filepath.Join(c.Root, dir.Name(), entry.Name())
			object, cursor, e := c.readFile(path)
			if e != nil {
				coverage = "UNKNOWN"
				object.Status = "UNKNOWN"
				object.Error = e.Error()
			}
			objects = append(objects, object)
			if cursor.info != nil {
				next[path] = cursor
			}
		}
	}
	c.cache = next
	return objects, coverage, nil
}

func (c *OCRVCollector) readFile(path string) (Object, fileCursor, error) {
	object := Object{SessionID: strings.TrimSuffix(filepath.Base(path), ".jsonl"), Source: path, Status: "UNKNOWN", Persisted: true}
	f, err := os.Open(path)
	if err != nil {
		return object, fileCursor{}, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return object, fileCursor{}, err
	}
	identity, err := SourceIdentity(f)
	if err != nil {
		return object, fileCursor{}, err
	}
	old, ok := c.cache[path]
	if ok && identity == old.object.SourceIdentity && info.Size() >= old.object.CompleteBytes && !(info.Size() == old.object.SourceBytes && info.ModTime().UTC().Format(time.RFC3339Nano) != old.object.SourceModifiedAt) {
		object = old.object
	}
	// Cursors are shared native-file facts, never evidence that this process
	// opened a writer. Only the current host's successful open hook can bind it.
	object.OwnerBound = false
	object.SourceBytes = info.Size()
	object.SourceModifiedAt = info.ModTime().UTC().Format(time.RFC3339Nano)
	object.SourceIdentity = identity
	if _, err = f.Seek(object.CompleteBytes, io.SeekStart); err != nil {
		return object, fileCursor{}, err
	}
	reader := bufio.NewReader(f)
	var parseErr error
	if object.Error != "" {
		parseErr = errors.New(object.Error)
	}
	for {
		line, e := reader.ReadBytes('\n')
		if e != nil {
			if e != io.EOF {
				parseErr = e
			}
			break
		}
		object.CompleteBytes += int64(len(line))
		object.EventCount++
		var record map[string]json.RawMessage
		if e = json.Unmarshal(line, &record); e != nil {
			parseErr = fmt.Errorf("invalid complete native record at byte %d", object.CompleteBytes)
			object.Status = "UNKNOWN"
			continue
		}
		var kind, at string
		json.Unmarshal(record["type"], &kind)
		json.Unmarshal(record["timestamp"], &at)
		var sessionID string
		json.Unmarshal(record["sessionId"], &sessionID)
		if sessionID != "" && sessionID != object.SessionID {
			parseErr = fmt.Errorf("native Session identity mismatch at byte %d", object.CompleteBytes)
			object.Status = "UNKNOWN"
			continue
		}
		if kind == "" {
			parseErr = fmt.Errorf("native record type missing at byte %d", object.CompleteBytes)
			object.Status = "UNKNOWN"
			continue
		}
		hash := sha256.Sum256(line)
		object.EventType = kind
		object.EventAt = at
		object.EventSHA256 = hex.EncodeToString(hash[:])
		object.EventSource = "OCRV_COMPLETE_NATIVE_JSONL_RECORD"
		object.Status = "UNKNOWN"
		if kind == "session_end" {
			object.Status = "CLOSED"
			var manifest struct {
				Schema string `json:"schema_version"`
				State  string `json:"terminal_state"`
			}
			if json.Unmarshal(record["run_manifest"], &manifest) == nil && manifest.Schema == "ocr.run-manifest/v1" {
				switch manifest.State {
				case "complete":
					object.Status = "COMPLETED"
				case "partial", "failed", "skipped":
					object.Status = strings.ToUpper(manifest.State)
				}
			}
		}
	}
	if parseErr != nil {
		object.Error = parseErr.Error()
		object.Status = "UNKNOWN"
	} else {
		object.Error = ""
	}
	if final, e := f.Stat(); e == nil {
		object.SourceBytes = final.Size()
		object.SourceModifiedAt = final.ModTime().UTC().Format(time.RFC3339Nano)
	} else {
		parseErr = e
		object.Status = "UNKNOWN"
		object.Error = e.Error()
	}
	return object, fileCursor{info: info, object: object}, parseErr
}

var registered struct {
	sync.Mutex
	sessions map[string]string
}

// RegisterOCRVSession is called only after the native writer successfully opens
// its exact file. A buffered event is never labelled durably written here.
func RegisterOCRVSession(id, path string) {
	registered.Lock()
	defer registered.Unlock()
	if registered.sessions == nil {
		registered.sessions = map[string]string{}
	}
	registered.sessions[path] = id
}

// StartOCRV is the small original-CLI lifecycle hook. It is not a daemon and
// adds no per-Run switch. Stop final-samples before returning from native run().
func StartOCRV() func() {
	home, err := os.UserHomeDir()
	if err != nil {
		fmt.Fprintln(os.Stderr, "slk-native-probe: native home unavailable:", err)
		return func() {}
	}
	host, err := NewHost("ocrv", filepath.Join(home, ".opencodereview"), os.Getpid())
	if err != nil {
		fmt.Fprintln(os.Stderr, "slk-native-probe:", err)
		return func() {}
	}
	collector := NewOCRVCollector(filepath.Join(host.NativeHome, "sessions"))
	root := DefaultRoot()
	if previous, e := Read(root, "ocrv"); e == nil {
		collector.Seed(previous)
	}
	done := make(chan struct{})
	exited := make(chan struct{})
	sample := func(lifecycle string) {
		objects, coverage, e := collector.Sample()
		host.ObservedAt = time.Now().UTC().Format(time.RFC3339Nano)
		host.Lifecycle = lifecycle
		host.Coverage = coverage
		host.Objects = objects
		host.Total = len(objects)
		host.Error = ""
		if e != nil {
			host.Error = e.Error()
		}
		registered.Lock()
		for i := range host.Objects {
			if id, ok := registered.sessions[host.Objects[i].Source]; ok && id == host.Objects[i].SessionID {
				host.Objects[i].OwnerBound = true
			}
		}
		registered.Unlock()
		if e = Merge(root, "ocrv", host); e != nil {
			fmt.Fprintln(os.Stderr, "slk-native-probe: sample not persisted:", e)
		}
	}
	sample("ACTIVE")
	go func() {
		defer close(exited)
		ticker := time.NewTicker(Interval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				sample("ACTIVE")
			case <-done:
				sample("EXITING")
				return
			}
		}
	}()
	var once sync.Once
	return func() { once.Do(func() { close(done); <-exited }) }
}
