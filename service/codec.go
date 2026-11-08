package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"unicode/utf8"
)

const (
	MaxPlan    = 200
	MaxCodeLen = 256 << 10 // fits 200 maximally escaped 128-character IDs
)

var (
	statusCode = map[string]byte{"maybe": 'a', "must": 'u', "skip": 's', "removed": 'r'}
	codeStatus = map[string]string{"a": "maybe", "u": "must", "s": "skip", "r": "removed"}
	errBadCode = errors.New("bad plan code")
)

// marshalJSON encodes like JSON.stringify: no HTML escaping, no trailing newline.
func marshalJSON(v any) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(b.Bytes(), []byte("\n")), nil
}

// EncodePlan returns base64url(JSON.stringify([[id, a|u|s|r], ...])) without
// padding, byte-identical to the legacy worker so codes stay interchangeable.
func EncodePlan(plan []PlanEntry) (string, error) {
	if len(plan) > MaxPlan {
		return "", errors.New("plan too long")
	}
	var b strings.Builder
	b.WriteByte('[')
	for i, p := range plan {
		c, ok := statusCode[p.Status]
		if !ok {
			return "", errors.New("invalid status")
		}
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteByte('[')
		jsString(&b, p.ID)
		b.WriteString(`,"`)
		b.WriteByte(c)
		b.WriteString(`"]`)
	}
	b.WriteByte(']')
	return base64.RawURLEncoding.EncodeToString([]byte(b.String())), nil
}

// jsString writes s exactly as JavaScript's JSON.stringify would.
func jsString(b *strings.Builder, s string) {
	const hex = "0123456789abcdef"
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		default:
			if r < 0x20 {
				b.WriteString(`\u00`)
				b.WriteByte(hex[r>>4])
				b.WriteByte(hex[r&0xf])
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

// DecodePlan accepts what the worker's atob-based decoder accepted (ASCII
// whitespace, optional '=' padding, either base64 alphabet) but validates
// statuses strictly. Every failure is reported as "bad plan code".
func DecodePlan(code string) ([]PlanEntry, error) {
	if len(code) > MaxCodeLen {
		return nil, errBadCode
	}
	s := strings.Map(func(r rune) rune {
		switch r {
		case ' ', '\t', '\n', '\f', '\r':
			return -1
		case '-':
			return '+'
		case '_':
			return '/'
		}
		return r
	}, code)
	if len(s)%4 == 0 {
		s = strings.TrimSuffix(s, "=")
		s = strings.TrimSuffix(s, "=")
	}
	if len(s)%4 == 1 {
		return nil, errBadCode
	}
	raw, err := base64.RawStdEncoding.DecodeString(s)
	if err != nil || !utf8.Valid(raw) {
		return nil, errBadCode
	}
	raw = bytes.TrimPrefix(raw, []byte("\xef\xbb\xbf")) // TextDecoder drops a BOM
	var items []json.RawMessage
	if err := json.Unmarshal(raw, &items); err != nil || items == nil || len(items) > MaxPlan {
		return nil, errBadCode
	}
	out := make([]PlanEntry, 0, len(items))
	for _, it := range items {
		var tup []json.RawMessage
		if err := json.Unmarshal(it, &tup); err != nil || len(tup) < 2 {
			return nil, errBadCode
		}
		var id, st string
		if !isJSONString(tup[0]) || !isJSONString(tup[1]) ||
			json.Unmarshal(tup[0], &id) != nil || json.Unmarshal(tup[1], &st) != nil {
			return nil, errBadCode
		}
		status, ok := codeStatus[st]
		if !ok {
			return nil, errBadCode
		}
		out = append(out, PlanEntry{ID: id, Status: status})
	}
	return out, nil
}

func isJSONString(r json.RawMessage) bool {
	r = bytes.TrimLeft(r, " \t\r\n")
	return len(r) > 0 && r[0] == '"'
}
