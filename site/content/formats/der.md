DER is the binary encoding of an X.509 certificate: the form a parser actually meets inside a
TLS handshake, a Java keystore or a certificate store, as opposed to the base64 text that gets
pasted into configuration files.

`der/self-signed-ed25519-cert.der` is a self-signed Ed25519 certificate for the reserved name
`fixture.example`, valid from 2020 to 2120 with a fixed serial number. It is byte for byte the
same certificate as the PEM fixture, just without the armour, so you can use the pair to test
that your code converts between the two encodings correctly.

The key is derived from a published seed, which means anyone can rebuild the certificate and
confirm it is what it claims to be. No private key is published, and the certificate names
only a reserved example domain, so it cannot be mistaken for a credential for a real host.

Use it to test certificate parsers, keystore importers and anything that has to detect the
encoding it was handed. Related format: [PEM](/pem).
