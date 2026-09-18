package api

// Keyring is a simple in-memory Authenticator backed by a key -> platform_id
// map (loaded from config). It satisfies the Authenticator interface used by
// the APIKeyAuth middleware.
type Keyring struct {
	keys map[string]string
}

// NewKeyring builds a Keyring from a key -> platform_id map.
func NewKeyring(keys map[string]string) *Keyring {
	cp := make(map[string]string, len(keys))
	for k, v := range keys {
		cp[k] = v
	}
	return &Keyring{keys: cp}
}

// PlatformForKey implements Authenticator.
func (k *Keyring) PlatformForKey(key string) (string, bool) {
	pid, ok := k.keys[key]
	return pid, ok
}

var _ Authenticator = (*Keyring)(nil)
