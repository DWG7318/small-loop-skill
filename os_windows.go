//go:build windows

package nativeprobe

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"unsafe"
)

var kernel = syscall.NewLazyDLL("kernel32.dll")
var createMutex = kernel.NewProc("CreateMutexW")
var waitObject = kernel.NewProc("WaitForSingleObject")
var releaseMutex = kernel.NewProc("ReleaseMutex")
var moveFileEx = kernel.NewProc("MoveFileExW")

func lockDirectory(dir string) (func(), error) {
	runtime.LockOSThread()
	dir, _ = filepath.Abs(dir)
	if resolved, err := filepath.EvalSymlinks(dir); err == nil {
		dir = resolved
	}
	dir = strings.ToLower(dir)
	hash := sha256.Sum256([]byte(dir))
	name, _ := syscall.UTF16PtrFromString("Local\\SLKNativeProbe-" + hex.EncodeToString(hash[:]))
	handle, _, err := createMutex.Call(0, 0, uintptr(unsafe.Pointer(name)))
	if handle == 0 {
		runtime.UnlockOSThread()
		return nil, err
	}
	status, _, err := waitObject.Call(handle, 0xffffffff)
	if status != 0 && status != 0x80 {
		syscall.CloseHandle(syscall.Handle(handle))
		runtime.UnlockOSThread()
		return nil, err
	}
	return func() {
		releaseMutex.Call(handle)
		syscall.CloseHandle(syscall.Handle(handle))
		runtime.UnlockOSThread()
	}, nil
}

func replaceFile(source, target string) error {
	a, _ := syscall.UTF16PtrFromString(source)
	b, _ := syscall.UTF16PtrFromString(target)
	ok, _, err := moveFileEx.Call(uintptr(unsafe.Pointer(a)), uintptr(unsafe.Pointer(b)), 1|8)
	if ok == 0 {
		return err
	}
	return nil
}

func ProcessIdentity(pid int) (string, error) {
	if pid <= 0 {
		return "", os.ErrNotExist
	}
	handle, err := syscall.OpenProcess(0x1000, false, uint32(pid))
	if err != nil {
		if err == syscall.Errno(87) {
			return "", os.ErrNotExist
		}
		return "", err
	}
	defer syscall.CloseHandle(handle)
	var created, exited, kernelTime, userTime syscall.Filetime
	if err = syscall.GetProcessTimes(handle, &created, &exited, &kernelTime, &userTime); err != nil {
		return "", err
	}
	if exited.HighDateTime != 0 || exited.LowDateTime != 0 {
		return "", os.ErrNotExist
	}
	return fmt.Sprintf("windows-filetime:%08x%08x", created.HighDateTime, created.LowDateTime), nil
}

func SourceIdentity(file *os.File) (string, error) {
	var info syscall.ByHandleFileInformation
	if err := syscall.GetFileInformationByHandle(syscall.Handle(file.Fd()), &info); err != nil {
		return "", err
	}
	return fmt.Sprintf("windows-file:%08x:%08x%08x", info.VolumeSerialNumber, info.FileIndexHigh, info.FileIndexLow), nil
}
