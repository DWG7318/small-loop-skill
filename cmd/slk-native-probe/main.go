package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	probe "github.com/DWG7318/slk-native-probe"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	flags := flag.NewFlagSet("slk-native-probe", flag.ContinueOnError)
	root := flags.String("root", probe.DefaultRoot(), "owned probe storage root")
	tool := flags.String("tool", "", "dsh or ocrv")
	session := flags.String("session", "", "exact native Session ID (query)")
	if err := flags.Parse(os.Args[1:]); err != nil {
		return err
	}
	if len(flags.Args()) != 1 {
		return fmt.Errorf("usage: slk-native-probe [--root path] --tool dsh|ocrv query|ingest")
	}
	switch flags.Args()[0] {
	case "query":
		s, err := probe.Read(*root, *tool)
		if err != nil {
			return err
		}
		if *session != "" {
			for id, h := range s.Hosts {
				objects := []probe.Object{}
				for _, o := range h.Objects {
					if o.SessionID == *session {
						objects = append(objects, o)
					}
				}
				h.Objects = objects
				s.Hosts[id] = h
			}
		}
		return json.NewEncoder(os.Stdout).Encode(s)
	case "ingest":
		if *tool != "dsh" {
			return fmt.Errorf("only native DSH plugin uses ingest")
		}
		var h probe.Host
		decoder := json.NewDecoder(os.Stdin)
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&h); err != nil {
			return err
		}
		actual, err := probe.NewHost("dsh", h.NativeHome, h.PID)
		if err != nil {
			return err
		}
		if h.ProcessCreated != "" && h.ProcessCreated != actual.ProcessCreated {
			return fmt.Errorf("native process identity changed")
		}
		h.ID = actual.ID
		h.ProcessCreated = actual.ProcessCreated
		h.Device = actual.Device
		h.NativeHome = actual.NativeHome
		if _, err := time.Parse(time.RFC3339Nano, h.ObservedAt); err != nil {
			return fmt.Errorf("native sample time is invalid: %w", err)
		}
		h.RecordedAt = time.Now().UTC().Format(time.RFC3339Nano)
		return probe.Merge(*root, *tool, h)
	default:
		return fmt.Errorf("unknown command")
	}
}
