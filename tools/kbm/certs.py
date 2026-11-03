"""Certificados SSL no Linux: o Python congelado (AppImage, feito no Ubuntu) nao acha o bundle de CAs do
Fedora/Bazzite e o download do cliente do Flet falha com CERTIFICATE_VERIFY_FAILED. Aponta SSL_CERT_FILE
para o bundle do sistema (ou o do certifi). No Windows o Python usa o repositorio do sistema."""
import os
import sys

CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/ssl/cert.pem",
)


def ensure_ca_bundle(environ=os.environ, isfile=os.path.isfile, platform=sys.platform, certifi_where=None):
    """Define SSL_CERT_FILE se preciso. Devolve o caminho definido, ou None (nada feito/nada achado)."""
    if not platform.startswith("linux"):
        return None
    if environ.get("SSL_CERT_FILE") or environ.get("SSL_CERT_DIR"):
        return None
    path = next((p for p in CA_BUNDLES if isfile(p)), None)
    if path is None:
        try:
            if certifi_where is None:
                import certifi
                certifi_where = certifi.where
            cand = certifi_where()
            if cand and isfile(cand):
                path = cand
        except ImportError:
            pass
    if path is None:
        return None
    environ["SSL_CERT_FILE"] = path
    return path
