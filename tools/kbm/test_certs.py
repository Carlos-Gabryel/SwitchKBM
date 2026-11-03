import certs


def run(environ, files=(), platform="linux", certifi_where=None):
    got = certs.ensure_ca_bundle(environ, lambda p: p in files, platform, certifi_where)
    return got, environ


def test_env_ja_definido_e_respeitado():
    for var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        got, env = run({var: "/x"}, files=certs.CA_BUNDLES)
        assert got is None and env == {var: "/x"}


def test_ordem_da_lista():
    got, env = run({}, files=certs.CA_BUNDLES)
    assert got == certs.CA_BUNDLES[0] and env["SSL_CERT_FILE"] == got
    got, _ = run({}, files=certs.CA_BUNDLES[2:])
    assert got == certs.CA_BUNDLES[2]


def test_fallback_certifi():
    got, env = run({}, files=("/c/cacert.pem",), certifi_where=lambda: "/c/cacert.pem")
    assert got == "/c/cacert.pem" and env["SSL_CERT_FILE"] == got


def test_certifi_arquivo_inexistente():
    got, env = run({}, certifi_where=lambda: "/nao/existe.pem")
    assert got is None and env == {}


def test_nada_encontrado():
    got, env = run({}, certifi_where=lambda: "")
    assert got is None and env == {}


def test_nao_linux_nao_toca():
    for plat in ("win32", "darwin"):
        got, env = run({}, files=certs.CA_BUNDLES, platform=plat)
        assert got is None and env == {}
