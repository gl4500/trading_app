"""
Generate a self-signed TLS certificate for localhost + Tailscale IP.
Saves cert.pem and key.pem to trading_app/certs/.
Run with: runtime\\python\\python.exe gen_certs.py
"""
import sys
import datetime
import ipaddress
import pathlib
import socket
import subprocess

# Ensure the self-contained site-packages is on the path
_SITE = pathlib.Path(__file__).parent / "site-packages"
if _SITE.exists() and str(_SITE) not in sys.path:
    sys.path.insert(0, str(_SITE))

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


def _detect_tailscale_ip() -> str | None:
    """Try to detect the Tailscale IPv4 address (100.x.x.x range)."""
    # Method 1: tailscale CLI
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=5
        )
        ip = result.stdout.strip()
        if ip and ip.startswith("100."):
            return ip
    except Exception:
        pass

    # Method 2: scan network interfaces for 100.x.x.x
    try:
        import socket
        hostname = socket.gethostname()
        addrs = socket.getaddrinfo(hostname, None)
        for addr in addrs:
            ip = addr[4][0]
            if ip.startswith("100."):
                return ip
    except Exception:
        pass

    return None


tailscale_ip = _detect_tailscale_ip()

san_entries = [
    x509.DNSName("localhost"),
    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
]

if tailscale_ip:
    san_entries.append(x509.IPAddress(ipaddress.IPv4Address(tailscale_ip)))
    print(f"Tailscale IP detected: {tailscale_ip} — including in certificate SANs.")
else:
    print("Tailscale IP not detected (Tailscale may not be running). Cert covers localhost only.")

print("Generating self-signed TLS certificate...")

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
    .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
    .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=825))
    .add_extension(
        x509.SubjectAlternativeName(san_entries),
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
print("  On first visit: click 'Advanced' → 'Proceed' to trust it.")
if tailscale_ip:
    print(f"  Access remotely at: https://{tailscale_ip}:5173")
