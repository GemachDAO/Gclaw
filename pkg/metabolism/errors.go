package metabolism

import "errors"

var (
	ErrInsufficientGMAC = errors.New("insufficient GMAC balance")
	ErrHibernating      = errors.New("agent is hibernating — GMAC balance critically low")
)
