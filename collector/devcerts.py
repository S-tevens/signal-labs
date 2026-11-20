"""Development TLS certificates: a private CA and a server certificate signed by it.

    python -m collector.devcerts                 # writes data/certs/{ca,server}.{pem,key}
    python -m collector.devcerts --san saas.internal --force

DEV ONLY. The CA key lives on disk unprotected. A real deployment uses certificates from the customer's or
platform's PKI, issued and rotated by a secrets manager. Never commit these files (data/ is git-ignored).

The collector trusts exactly this CA (SAAS_CA_FILE) and always verifies the server name, so a man in the middle
presenting any other certificate is rejected.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_SANS = ("localhost", "127.0.0.1", "::1")
FILES = ("ca.pem", "ca.key", "server.pem", "server.key")


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as exc:
        raise SystemExit("The 'cryptography' package is needed to make dev certificates: pip install cryptography") from exc
    return x509, hashes, serialization, ec, ExtendedKeyUsageOID, NameOID


def _san(x509, value: str):
    try:
        return x509.IPAddress(ipaddress.ip_address(value))
    except ValueError:
        return x509.DNSName(value)


def generate(out_dir: str | Path = "data/certs", sans=DEFAULT_SANS, days: int = 365, force: bool = False) -> dict[str, Path]:
    out = Path(out_dir)
    paths = {name: out / name for name in FILES}
    if not force and all(p.exists() for p in paths.values()):
        return paths
    x509, hashes, serialization, ec, EKU, NameOID = _crypto()
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc) - timedelta(minutes=5)  # tolerate small clock differences

    def name(cn):
        return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Signal Labs (dev)"), x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name("Signal Labs Dev CA"))
        .issuer_name(name("Signal Labs Dev CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                          key_encipherment=False, data_encipherment=False, key_agreement=False,
                          encipher_only=False, decipher_only=False),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    srv_key = ec.generate_private_key(ec.SECP256R1())
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(name("signal-labs-saas"))
        .issuer_name(ca_cert.subject)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([_san(x509, s) for s in sans]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([EKU.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    def write_key(path: Path, key):
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        try:
            os.chmod(path, 0o600)  # best effort; Windows ignores most mode bits
        except OSError:
            pass

    paths["ca.pem"].write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    write_key(paths["ca.key"], ca_key)
    paths["server.pem"].write_bytes(srv_cert.public_bytes(serialization.Encoding.PEM))
    write_key(paths["server.key"], srv_key)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/certs")
    ap.add_argument("--san", action="append", default=[], help="extra DNS name or IP the server certificate must cover")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--force", action="store_true", help="replace existing certificates")
    args = ap.parse_args()
    paths = generate(args.out, tuple(dict.fromkeys([*DEFAULT_SANS, *args.san])), args.days, args.force)
    for name, p in paths.items():
        print(f"{name:11} {p}")
    print("Collector: SAAS_CA_FILE=" + str(paths["ca.pem"]) + "  REQUIRE_TLS=1")
    print("SaaS:      uvicorn ... --ssl-keyfile " + str(paths["server.key"]) + " --ssl-certfile " + str(paths["server.pem"]))


if __name__ == "__main__":
    main()
