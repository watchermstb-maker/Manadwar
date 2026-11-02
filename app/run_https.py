"""Run the app over HTTPS with a self-signed certificate (for testing the
live camera scanner on a phone).

    python -m app.run_https               # https://<this PC's address>:8443/

Browsers only allow camera access on localhost or HTTPS. A self-signed
certificate makes the phone show a warning once ("Advanced" > "Proceed"); after
that, the guard's live QR scanner works. For a real deployment use a proper
certificate (for example a reverse proxy such as Caddy or nginx).
"""
import argparse
import datetime
import ipaddress
import socket
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def lan_addresses():
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # no packet is sent; picks the outbound interface
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


def make_cert(folder: Path, extra_ips):
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / "dev-cert.pem", folder / "dev-key.pem"
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ManaDwar dev")])
    sans = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    sans += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in extra_ips]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run ManaDwar over HTTPS (self-signed).")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--certs", default="certs")
    args = parser.parse_args(argv)

    ips = lan_addresses()
    cert, key = make_cert(Path(args.certs), ips)
    print("Open one of these (accept the browser's certificate warning once):")
    print(f"  https://localhost:{args.port}/")
    for ip in ips:
        print(f"  https://{ip}:{args.port}/")
    uvicorn.run("app.main:app", host=args.host, port=args.port, ssl_certfile=str(cert), ssl_keyfile=str(key))


if __name__ == "__main__":
    main()
