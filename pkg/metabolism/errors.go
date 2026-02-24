package metabolism

import "errors"

var ErrInsufficientGMAC = errors.New("insufficient GMAC balance")
var ErrHibernating = errors.New("agent is hibernating — GMAC balance critically low")
