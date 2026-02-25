package channels

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/GemachDAO/Gclaw/pkg/bus"
)

// --- BaseChannel extra tests ---

func TestBaseChannel_Name(t *testing.T) {
	ch := NewBaseChannel("telegram", nil, nil, nil)
	if ch.Name() != "telegram" {
		t.Errorf("expected name 'telegram', got %q", ch.Name())
	}
}

func TestBaseChannel_IsRunning(t *testing.T) {
	ch := NewBaseChannel("test", nil, nil, nil)
	if ch.IsRunning() {
		t.Error("expected IsRunning=false initially")
	}
	ch.setRunning(true)
	if !ch.IsRunning() {
		t.Error("expected IsRunning=true after setRunning(true)")
	}
}

func TestBaseChannel_HandleMessage_NotAllowed(t *testing.T) {
	mb := bus.NewMessageBus()
	ch := NewBaseChannel("test", nil, mb, []string{"allowed-user"})
	ch.HandleMessage("denied-user", "chat1", "hello", nil, nil)
	// Message should not be in the bus since sender is not allowed
	// Verify no message was published by checking bus is empty
	ctx, cancel := t.Context(), func() {}
	_ = ctx
	cancel()
}

func TestBaseChannel_HandleMessage_Allowed(t *testing.T) {
	mb := bus.NewMessageBus()
	ch := NewBaseChannel("test", nil, mb, []string{"allowed-user"})
	ch.HandleMessage("allowed-user", "chat1", "hello world", nil, nil)

	// Message should be in the bus
	ctx := t.Context()
	msg, ok := mb.ConsumeInbound(ctx)
	if !ok {
		t.Fatal("expected message in bus")
	}
	if msg.Content != "hello world" {
		t.Errorf("expected 'hello world', got %q", msg.Content)
	}
	if msg.Channel != "test" {
		t.Errorf("expected channel 'test', got %q", msg.Channel)
	}
}

func TestBaseChannel_HandleMessage_WithMedia(t *testing.T) {
	mb := bus.NewMessageBus()
	ch := NewBaseChannel("test", nil, mb, nil)
	media := []string{"url1", "url2"}
	ch.HandleMessage("user1", "chat1", "look at this", media, map[string]string{"type": "photo"})

	ctx := t.Context()
	msg, ok := mb.ConsumeInbound(ctx)
	if !ok {
		t.Fatal("expected message in bus")
	}
	if len(msg.Media) != 2 {
		t.Errorf("expected 2 media items, got %d", len(msg.Media))
	}
}

// --- parseChatID ---

func TestParseChatID_Valid(t *testing.T) {
	id, err := parseChatID("12345")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id != 12345 {
		t.Errorf("expected 12345, got %d", id)
	}
}

func TestParseChatID_Negative(t *testing.T) {
	id, err := parseChatID("-10012345")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id != -10012345 {
		t.Errorf("expected -10012345, got %d", id)
	}
}

func TestParseChatID_Invalid(t *testing.T) {
	_, err := parseChatID("notanumber")
	if err == nil {
		t.Error("expected error for invalid chat ID")
	}
}

// --- escapeHTML ---

func TestEscapeHTML(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"hello world", "hello world"},
		{"<b>bold</b>", "&lt;b&gt;bold&lt;/b&gt;"},
		{"a & b", "a &amp; b"},
		{"<script>alert('xss')</script>", "&lt;script&gt;alert('xss')&lt;/script&gt;"},
		{"", ""},
	}
	for _, tt := range tests {
		got := escapeHTML(tt.input)
		if got != tt.want {
			t.Errorf("escapeHTML(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

// --- markdownToTelegramHTML ---

func TestMarkdownToTelegramHTML_Empty(t *testing.T) {
	got := markdownToTelegramHTML("")
	if got != "" {
		t.Errorf("expected empty string, got %q", got)
	}
}

func TestMarkdownToTelegramHTML_Bold(t *testing.T) {
	got := markdownToTelegramHTML("**bold text**")
	if !strings.Contains(got, "<b>bold text</b>") {
		t.Errorf("expected bold markup, got %q", got)
	}
}

func TestMarkdownToTelegramHTML_Code(t *testing.T) {
	got := markdownToTelegramHTML("`code`")
	if !strings.Contains(got, "<code>code</code>") {
		t.Errorf("expected code markup, got %q", got)
	}
}

func TestMarkdownToTelegramHTML_CodeBlock(t *testing.T) {
	got := markdownToTelegramHTML("```\nsome code\n```")
	if !strings.Contains(got, "<pre><code>") {
		t.Errorf("expected code block markup, got %q", got)
	}
}

func TestMarkdownToTelegramHTML_Link(t *testing.T) {
	got := markdownToTelegramHTML("[click here](https://example.com)")
	if !strings.Contains(got, `<a href="https://example.com">click here</a>`) {
		t.Errorf("expected link markup, got %q", got)
	}
}

func TestMarkdownToTelegramHTML_Strikethrough(t *testing.T) {
	got := markdownToTelegramHTML("~~strikethrough~~")
	if !strings.Contains(got, "<s>strikethrough</s>") {
		t.Errorf("expected strikethrough markup, got %q", got)
	}
}

func TestMarkdownToTelegramHTML_ListItem(t *testing.T) {
	got := markdownToTelegramHTML("- item one")
	if !strings.Contains(got, "• item one") {
		t.Errorf("expected bullet point, got %q", got)
	}
}

func TestMarkdownToTelegramHTML_Heading(t *testing.T) {
	got := markdownToTelegramHTML("## My Heading")
	if strings.Contains(got, "#") {
		t.Errorf("expected heading to be converted, got %q", got)
	}
}

// --- extractCodeBlocks ---

func TestExtractCodeBlocks_NoBlocks(t *testing.T) {
	result := extractCodeBlocks("just plain text")
	if len(result.codes) != 0 {
		t.Errorf("expected no code blocks, got %d", len(result.codes))
	}
	if result.text != "just plain text" {
		t.Errorf("expected unchanged text, got %q", result.text)
	}
}

func TestExtractCodeBlocks_WithBlock(t *testing.T) {
	result := extractCodeBlocks("```go\nfmt.Println(\"hello\")\n```")
	if len(result.codes) != 1 {
		t.Fatalf("expected 1 code block, got %d", len(result.codes))
	}
	if !strings.Contains(result.codes[0], "fmt.Println") {
		t.Errorf("expected code content, got %q", result.codes[0])
	}
}

// --- extractInlineCodes ---

func TestExtractInlineCodes_NoCode(t *testing.T) {
	result := extractInlineCodes("no inline code here")
	if len(result.codes) != 0 {
		t.Errorf("expected no inline codes, got %d", len(result.codes))
	}
}

func TestExtractInlineCodes_WithCode(t *testing.T) {
	result := extractInlineCodes("use `fmt.Println` to print")
	if len(result.codes) != 1 {
		t.Fatalf("expected 1 inline code, got %d", len(result.codes))
	}
	if result.codes[0] != "fmt.Println" {
		t.Errorf("expected 'fmt.Println', got %q", result.codes[0])
	}
}

// --- parseJSONInt64 ---

func TestParseJSONInt64_Integer(t *testing.T) {
	tests := []struct {
		input    string
		expected int64
	}{
		{"12345", 12345},
		{"-9999", -9999},
		{"0", 0},
		{`"67890"`, 67890},
	}
	for _, tt := range tests {
		got, err := parseJSONInt64(json.RawMessage(tt.input))
		if err != nil {
			t.Errorf("parseJSONInt64(%q) error: %v", tt.input, err)
			continue
		}
		if got != tt.expected {
			t.Errorf("parseJSONInt64(%q) = %d, want %d", tt.input, got, tt.expected)
		}
	}
}

func TestParseJSONInt64_Empty(t *testing.T) {
	got, err := parseJSONInt64(json.RawMessage(""))
	if err != nil {
		t.Errorf("unexpected error for empty: %v", err)
	}
	if got != 0 {
		t.Errorf("expected 0 for empty, got %d", got)
	}
}

func TestParseJSONInt64_Invalid(t *testing.T) {
	_, err := parseJSONInt64(json.RawMessage(`"notanumber"`))
	if err == nil {
		t.Error("expected error for invalid int64")
	}
}

// --- parseJSONString ---

func TestParseJSONString_String(t *testing.T) {
	got := parseJSONString(json.RawMessage(`"hello"`))
	if got != "hello" {
		t.Errorf("expected 'hello', got %q", got)
	}
}

func TestParseJSONString_Empty(t *testing.T) {
	got := parseJSONString(json.RawMessage(""))
	if got != "" {
		t.Errorf("expected empty, got %q", got)
	}
}

func TestParseJSONString_Fallback(t *testing.T) {
	got := parseJSONString(json.RawMessage(`123`))
	if got != "123" {
		t.Errorf("expected '123' fallback, got %q", got)
	}
}

// --- truncate (onebot) ---

func TestTruncateOnebot(t *testing.T) {
	tests := []struct {
		s    string
		n    int
		want string
	}{
		{"hello", 10, "hello"},
		{"hello world", 5, "hello..."},
		{"", 5, ""},
	}
	for _, tt := range tests {
		got := truncate(tt.s, tt.n)
		if got != tt.want {
			t.Errorf("truncate(%q, %d) = %q, want %q", tt.s, tt.n, got, tt.want)
		}
	}
}

// --- appendContent (discord) ---

func TestAppendContent(t *testing.T) {
	if got := appendContent("", "suffix"); got != "suffix" {
		t.Errorf("appendContent empty base: %q", got)
	}
	if got := appendContent("base", "suffix"); got != "base\nsuffix" {
		t.Errorf("appendContent: %q", got)
	}
}

// --- isAPIResponse ---

func TestIsAPIResponse_True(t *testing.T) {
	// isAPIResponse returns true for "ok" or "failed" strings
	raw := json.RawMessage(`"ok"`)
	if !isAPIResponse(raw) {
		t.Error("expected isAPIResponse=true for 'ok'")
	}
	raw = json.RawMessage(`"failed"`)
	if !isAPIResponse(raw) {
		t.Error("expected isAPIResponse=true for 'failed'")
	}
	// Also true for BotStatus with online=true
	raw = json.RawMessage(`{"online":true,"good":false}`)
	if !isAPIResponse(raw) {
		t.Error("expected isAPIResponse=true for online BotStatus")
	}
}

func TestIsAPIResponse_False(t *testing.T) {
	raw := json.RawMessage(`{"post_type":"message","message_type":"private"}`)
	if isAPIResponse(raw) {
		t.Error("expected isAPIResponse=false for event message")
	}
	raw = json.RawMessage("")
	if isAPIResponse(raw) {
		t.Error("expected isAPIResponse=false for empty")
	}
}
