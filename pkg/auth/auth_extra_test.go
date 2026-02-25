package auth

import (
	"os"
	"strings"
	"testing"
)

func TestDeleteAllCredentials(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	cred := &AuthCredential{AccessToken: "token", Provider: "openai", AuthMethod: "oauth"}
	if err := SetCredential("openai", cred); err != nil {
		t.Fatalf("SetCredential: %v", err)
	}

	if err := DeleteAllCredentials(); err != nil {
		t.Fatalf("DeleteAllCredentials: %v", err)
	}

	// Load again should return empty store
	store, err := LoadStore()
	if err != nil {
		t.Fatalf("LoadStore: %v", err)
	}
	if len(store.Credentials) != 0 {
		t.Errorf("expected empty credentials after DeleteAll, got %d", len(store.Credentials))
	}
}

func TestDeleteAllCredentials_NoFile(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	// Should not error if file doesn't exist
	err := DeleteAllCredentials()
	if err != nil {
		t.Fatalf("expected no error when auth file doesn't exist: %v", err)
	}
}

func TestGeneratePKCE_Uniqueness(t *testing.T) {
	codes1, err := GeneratePKCE()
	if err != nil {
		t.Fatalf("GeneratePKCE: %v", err)
	}
	codes2, err := GeneratePKCE()
	if err != nil {
		t.Fatalf("GeneratePKCE: %v", err)
	}
	if codes1.CodeVerifier == codes2.CodeVerifier {
		t.Error("expected unique code verifiers")
	}
	if codes1.CodeChallenge == codes2.CodeChallenge {
		t.Error("expected unique code challenges")
	}
}

func TestLoginPasteToken_Success(t *testing.T) {
	reader := strings.NewReader("sk-test-token-12345\n")
	cred, err := LoginPasteToken("openai", reader)
	if err != nil {
		t.Fatalf("LoginPasteToken: %v", err)
	}
	if cred.AccessToken != "sk-test-token-12345" {
		t.Errorf("expected 'sk-test-token-12345', got %q", cred.AccessToken)
	}
	if cred.Provider != "openai" {
		t.Errorf("expected provider 'openai', got %q", cred.Provider)
	}
	if cred.AuthMethod != "token" {
		t.Errorf("expected auth_method 'token', got %q", cred.AuthMethod)
	}
}

func TestLoginPasteToken_EmptyToken(t *testing.T) {
	reader := strings.NewReader("   \n")
	_, err := LoginPasteToken("anthropic", reader)
	if err == nil {
		t.Error("expected error for empty token")
	}
}

func TestLoginPasteToken_NoInput(t *testing.T) {
	reader := strings.NewReader("")
	_, err := LoginPasteToken("openai", reader)
	if err == nil {
		t.Error("expected error for empty input")
	}
}

func TestProviderDisplayName(t *testing.T) {
	tests := []struct {
		provider string
		contains string
	}{
		{"anthropic", "anthropic"},
		{"openai", "openai"},
		{"custom", "custom"},
	}
	for _, tt := range tests {
		got := providerDisplayName(tt.provider)
		if !strings.Contains(got, tt.contains) {
			t.Errorf("providerDisplayName(%q) = %q, expected to contain %q", tt.provider, got, tt.contains)
		}
	}
}

func TestSaveStore_FilePermissions(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	store := &AuthStore{
		Credentials: map[string]*AuthCredential{
			"test": {AccessToken: "secret", Provider: "test"},
		},
	}
	if err := SaveStore(store); err != nil {
		t.Fatalf("SaveStore: %v", err)
	}

	info, err := os.Stat(authFilePath())
	if err != nil {
		t.Fatalf("Stat: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("expected 0600 permissions, got %o", info.Mode().Perm())
	}
}

func TestGetCredential_NotFound(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	cred, err := GetCredential("nonexistent")
	if err != nil {
		t.Fatalf("GetCredential: %v", err)
	}
	if cred != nil {
		t.Error("expected nil for nonexistent provider")
	}
}
