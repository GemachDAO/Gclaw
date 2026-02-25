package events

import (
	"strings"
	"testing"
)

func TestFormatMessage_Add(t *testing.T) {
	ev := &DeviceEvent{
		Action:  ActionAdd,
		Kind:    KindUSB,
		Vendor:  "Apple Inc.",
		Product: "Magic Mouse",
		Serial:  "SN123",
	}
	msg := ev.FormatMessage()
	if !strings.Contains(msg, "Connected") {
		t.Errorf("expected 'Connected' in add message, got: %s", msg)
	}
	if !strings.Contains(msg, "Apple Inc.") {
		t.Errorf("expected vendor in message, got: %s", msg)
	}
	if !strings.Contains(msg, "Magic Mouse") {
		t.Errorf("expected product in message, got: %s", msg)
	}
	if !strings.Contains(msg, "SN123") {
		t.Errorf("expected serial in message, got: %s", msg)
	}
}

func TestFormatMessage_Remove(t *testing.T) {
	ev := &DeviceEvent{
		Action:  ActionRemove,
		Kind:    KindUSB,
		Vendor:  "SanDisk",
		Product: "Ultra USB 3.0",
	}
	msg := ev.FormatMessage()
	if !strings.Contains(msg, "Disconnected") {
		t.Errorf("expected 'Disconnected' in remove message, got: %s", msg)
	}
}

func TestFormatMessage_WithCapabilities(t *testing.T) {
	ev := &DeviceEvent{
		Action:       ActionAdd,
		Kind:         KindUSB,
		Vendor:       "Vendor",
		Product:      "Product",
		Capabilities: "Mass Storage",
	}
	msg := ev.FormatMessage()
	if !strings.Contains(msg, "Mass Storage") {
		t.Errorf("expected capabilities in message, got: %s", msg)
	}
}

func TestFormatMessage_NoSerial(t *testing.T) {
	ev := &DeviceEvent{
		Action:  ActionAdd,
		Kind:    KindBluetooth,
		Vendor:  "Microsoft",
		Product: "Wireless Keyboard",
	}
	msg := ev.FormatMessage()
	if strings.Contains(msg, "Serial:") {
		t.Errorf("expected no serial in message, got: %s", msg)
	}
	if !strings.Contains(msg, "bluetooth") {
		t.Errorf("expected kind 'bluetooth' in message, got: %s", msg)
	}
}

func TestActionConstants(t *testing.T) {
	if ActionAdd != "add" {
		t.Errorf("expected ActionAdd='add', got %q", ActionAdd)
	}
	if ActionRemove != "remove" {
		t.Errorf("expected ActionRemove='remove', got %q", ActionRemove)
	}
	if ActionChange != "change" {
		t.Errorf("expected ActionChange='change', got %q", ActionChange)
	}
}

func TestKindConstants(t *testing.T) {
	if KindUSB != "usb" {
		t.Errorf("expected KindUSB='usb', got %q", KindUSB)
	}
	if KindBluetooth != "bluetooth" {
		t.Errorf("expected KindBluetooth='bluetooth', got %q", KindBluetooth)
	}
	if KindPCI != "pci" {
		t.Errorf("expected KindPCI='pci', got %q", KindPCI)
	}
	if KindGeneric != "generic" {
		t.Errorf("expected KindGeneric='generic', got %q", KindGeneric)
	}
}
