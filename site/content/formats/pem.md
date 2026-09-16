PEM is the base64 armour around a certificate — the form that gets pasted into configuration
files, environment variables and deployment scripts, wrapped in `BEGIN` and `END` lines.

`pem/self-signed-ed25519-cert.pem` is a self-signed Ed25519 certificate for the reserved name
`fixture.example`, valid from 2020 to 2120 with a fixed serial. Ed25519 is the modern choice
and is still refused by older libraries, which makes it useful for finding out what your stack
actually supports.

The key is derived from a published seed, so anyone can rebuild the certificate and verify it
is what it claims to be. No private key is published here — a validator refuses any fixture
containing one — and the certificate names only a reserved example domain, so it can never be
mistaken for a credential belonging to a real host.

Use it to test certificate parsing, trust-store loading, expiry handling and error messages
for an untrusted chain. Related format: [DER](/der), the same certificate in binary.
