"""
Generate a self-signed TLS certificate for localhost.
Saves cert.pem and key.pem to trading_app/certs/.
Run with: runtime\python\python.exe gen_certs.py
"""
import datetime
import ipaddress
import pathlib

ROOT = pathlib.Path(__file__).parent
CERTS_DIR = ROOT / "certs"
CERTS_DIR.mkdir(exist_ok=True)

CERT_FILE = CERTS_DIR / "cert.pem"
KEY_FILE  = CERTS_DIR / "key.pem"

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    print("[ERROR] cryptography package not found.")
    print("  Run: pip install cryptography")
    raise SystemExit(1)

print("Generating self-signed TLS certificate for localhost...")

# Generate RSA private key
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

# Save private key (no passphrase — uvicorn/vite need to read it unattended)
KEY_FILE.write_bytes(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
))

# Build certificate
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AI Trading App (local)"),
])

cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
    .add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]),
        critical=False,
    )
    .add_extension(
        x509.BasicConstraints(ca=False, path_length=None),
        critical=True,
    )
    .sign(key, hashes.SHA256())
)

CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

print(f"  cert.pem = {CERT_FILE}")
print(f"  key.pem  = {KEY_FILE}")
print("Done. Certificate is valid for 825 days.")
print()
print("NOTE: Browsers will show a security warning for self-signed certs.")
print("  Click 'Advanced' → 'Proceed to localhost' to continue.")
