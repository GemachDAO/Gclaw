package utils

import (
	"archive/zip"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// --- DerefStr ---

func TestDerefStr_NonNil(t *testing.T) {
	s := "hello"
	got := DerefStr(&s, "fallback")
	if got != "hello" {
		t.Errorf("expected 'hello', got %q", got)
	}
}

func TestDerefStr_Nil(t *testing.T) {
	got := DerefStr(nil, "fallback")
	if got != "fallback" {
		t.Errorf("expected 'fallback', got %q", got)
	}
}

func TestDerefStr_EmptyString(t *testing.T) {
	s := ""
	got := DerefStr(&s, "fallback")
	if got != "" {
		t.Errorf("expected empty string, got %q", got)
	}
}

// --- IsAudioFile ---

func TestIsAudioFile_ByExtension(t *testing.T) {
	tests := []struct {
		filename string
		want     bool
	}{
		{"audio.mp3", true},
		{"audio.wav", true},
		{"audio.ogg", true},
		{"audio.m4a", true},
		{"audio.flac", true},
		{"audio.aac", true},
		{"audio.wma", true},
		{"AUDIO.MP3", true}, // case-insensitive
		{"image.png", false},
		{"document.pdf", false},
		{"video.mp4", false},
		{"", false},
	}

	for _, tt := range tests {
		t.Run(tt.filename, func(t *testing.T) {
			got := IsAudioFile(tt.filename, "")
			if got != tt.want {
				t.Errorf("IsAudioFile(%q, '') = %v, want %v", tt.filename, got, tt.want)
			}
		})
	}
}

func TestIsAudioFile_ByContentType(t *testing.T) {
	tests := []struct {
		contentType string
		want        bool
	}{
		{"audio/mpeg", true},
		{"audio/ogg", true},
		{"application/ogg", true},
		{"application/x-ogg", true},
		{"AUDIO/MPEG", true}, // case-insensitive
		{"image/png", false},
		{"text/plain", false},
		{"", false},
	}

	for _, tt := range tests {
		t.Run(tt.contentType, func(t *testing.T) {
			got := IsAudioFile("unknown.bin", tt.contentType)
			if got != tt.want {
				t.Errorf("IsAudioFile('unknown.bin', %q) = %v, want %v", tt.contentType, got, tt.want)
			}
		})
	}
}

// --- SanitizeFilename ---

func TestSanitizeFilename(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"file.txt", "file.txt"},
		{"/path/to/file.txt", "file.txt"},
		{"path/../etc/passwd", "passwd"},         // filepath.Base extracts last component
		{"file with spaces.txt", "file with spaces.txt"},
		{"file/with/slashes.txt", "slashes.txt"}, // filepath.Base extracts last component
		{"windows\\path.txt", "windows_path.txt"},
	}

	for _, tt := range tests {
		got := SanitizeFilename(tt.input)
		if got != tt.want {
			t.Errorf("SanitizeFilename(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

// --- ValidateSkillIdentifier ---

func TestValidateSkillIdentifier(t *testing.T) {
	tests := []struct {
		input   string
		wantErr bool
	}{
		{"my-skill", false},
		{"skill_name", false},
		{"skill123", false},
		{"", true},
		{"   ", true},
		{"skill/path", true},
		{"skill\\path", true},
		{"../etc/passwd", true},
		{"skill..name", true},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			err := ValidateSkillIdentifier(tt.input)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateSkillIdentifier(%q) error=%v, wantErr=%v", tt.input, err, tt.wantErr)
			}
		})
	}
}

// --- DownloadToFile ---

func TestDownloadToFile_Success(t *testing.T) {
	content := "test file content"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(content))
	}))
	defer server.Close()

	req, _ := http.NewRequest("GET", server.URL, nil)
	path, err := DownloadToFile(context.Background(), &http.Client{}, req, 0)
	if err != nil {
		t.Fatalf("DownloadToFile failed: %v", err)
	}
	defer os.Remove(path)

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read downloaded file: %v", err)
	}
	if string(data) != content {
		t.Errorf("expected %q, got %q", content, string(data))
	}
}

func TestDownloadToFile_HTTPError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer server.Close()

	req, _ := http.NewRequest("GET", server.URL, nil)
	_, err := DownloadToFile(context.Background(), &http.Client{}, req, 0)
	if err == nil {
		t.Error("expected error for HTTP 404")
	}
}

func TestDownloadToFile_MaxBytes(t *testing.T) {
	content := strings.Repeat("X", 200)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(content))
	}))
	defer server.Close()

	req, _ := http.NewRequest("GET", server.URL, nil)
	_, err := DownloadToFile(context.Background(), &http.Client{}, req, 100)
	if err == nil {
		t.Error("expected error when download exceeds maxBytes")
	}
}

func TestDownloadToFile_WithinMaxBytes(t *testing.T) {
	content := "small content"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(content))
	}))
	defer server.Close()

	req, _ := http.NewRequest("GET", server.URL, nil)
	path, err := DownloadToFile(context.Background(), &http.Client{}, req, 1000)
	if err != nil {
		t.Fatalf("DownloadToFile failed: %v", err)
	}
	defer os.Remove(path)

	data, _ := os.ReadFile(path)
	if string(data) != content {
		t.Errorf("expected %q, got %q", content, string(data))
	}
}

// --- ExtractZipFile ---

func createTestZip(t *testing.T, entries map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "test.zip")

	f, err := os.Create(zipPath)
	if err != nil {
		t.Fatalf("create zip file: %v", err)
	}
	defer f.Close()

	w := zip.NewWriter(f)
	defer w.Close()

	for name, content := range entries {
		entry, err := w.Create(name)
		if err != nil {
			t.Fatalf("create zip entry %q: %v", name, err)
		}
		io.WriteString(entry, content)
	}

	return zipPath
}

func TestExtractZipFile_Success(t *testing.T) {
	zipPath := createTestZip(t, map[string]string{
		"file1.txt":        "content1",
		"subdir/file2.txt": "content2",
	})

	targetDir := t.TempDir()
	err := ExtractZipFile(zipPath, targetDir)
	if err != nil {
		t.Fatalf("ExtractZipFile failed: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(targetDir, "file1.txt"))
	if err != nil {
		t.Fatalf("expected file1.txt to be extracted: %v", err)
	}
	if string(data) != "content1" {
		t.Errorf("expected 'content1', got %q", string(data))
	}

	data, err = os.ReadFile(filepath.Join(targetDir, "subdir", "file2.txt"))
	if err != nil {
		t.Fatalf("expected subdir/file2.txt to be extracted: %v", err)
	}
	if string(data) != "content2" {
		t.Errorf("expected 'content2', got %q", string(data))
	}
}

func TestExtractZipFile_InvalidPath(t *testing.T) {
	err := ExtractZipFile("/nonexistent/path.zip", t.TempDir())
	if err == nil {
		t.Error("expected error for nonexistent zip file")
	}
}

func TestExtractZipFile_PathTraversal(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "malicious.zip")

	f, _ := os.Create(zipPath)
	w := zip.NewWriter(f)
	entry, _ := w.Create("../../../etc/passwd")
	entry.Write([]byte("malicious"))
	w.Close()
	f.Close()

	err := ExtractZipFile(zipPath, filepath.Join(dir, "target"))
	if err == nil {
		t.Error("expected error for path traversal in zip")
	}
}
