from itb.redact import redact, redact_obj, REDACTED

FAKE_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"


def test_key_value_password():
    assert "hunter2" not in redact("db password=hunter2 failed")


def test_json_style_secret():
    out = redact('{"api_key": "abc123secret", "user": "bob"}')
    assert "abc123secret" not in out
    assert "bob" in out


def test_bearer_token():
    out = redact("Authorization: Bearer abcdefghijklmnop1234")
    assert "abcdefghijklmnop1234" not in out


def test_github_token():
    assert FAKE_TOKEN not in redact(f"pushed with {FAKE_TOKEN}")


def test_aws_key():
    assert FAKE_AWS not in redact(f"key {FAKE_AWS} used")


def test_url_password():
    out = redact("connect postgres://app:s3cretpw@db:5432/x")
    assert "s3cretpw" not in out
    assert "app" in out and "@db:5432" in out


def test_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert "MIIabc" not in redact(pem)


def test_plain_text_untouched():
    msg = "deploy v2 to web finished in 12s"
    assert redact(msg) == msg


def test_redact_obj_nested():
    out = redact_obj({"a": ["token=xyz999"], "b": {"c": "ok"}})
    assert "xyz999" not in str(out)
    assert out["b"]["c"] == "ok"


def test_non_string_passthrough():
    assert redact(42) == 42
    assert REDACTED == "[REDACTED]"
