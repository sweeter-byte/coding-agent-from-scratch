from security import SensitiveDataPolicy


def test_sensitive_path_detection_blocks_credentials_but_allows_templates():
    policy = SensitiveDataPolicy()

    assert policy.is_sensitive_path(".env") is True
    assert policy.is_sensitive_path("config/.env.local") is True
    assert policy.is_sensitive_path(".ssh/id_ed25519") is True
    assert policy.is_sensitive_path("certs/server.pem") is True
    assert policy.is_sensitive_path("certs/server.key") is True
    assert policy.is_sensitive_path(".env.example") is False
    assert policy.is_sensitive_path("src/config.py") is False


def test_redact_text_masks_assignment_bearer_and_known_token():
    policy = SensitiveDataPolicy()
    fake_token = "sk-FAKE_TEST_TOKEN_1234567890"

    text = (
        "OPENAI_API_KEY=definitely-not-a-real-key\n"
        "AWS_SECRET_ACCESS_KEY=definitely-not-a-real-secret\n"
        "Authorization: Bearer abcdefghijklmnop\n"
        f"raw={fake_token}\n"
    )

    redacted = policy.redact_text(text)

    assert "definitely-not-a-real-key" not in redacted
    assert "definitely-not-a-real-secret" not in redacted
    assert "abcdefghijklmnop" not in redacted
    assert fake_token not in redacted
    assert "OPENAI_API_KEY=[REDACTED]" in redacted
    assert "Bearer [REDACTED]" in redacted


def test_redact_data_uses_sensitive_keys_recursively():
    policy = SensitiveDataPolicy()

    result = policy.redact_data(
        {
            "safe": "visible",
            "api_key": "abc",
            "nested": {
                "github_token": "def",
            },
        }
    )

    assert result["safe"] == "visible"
    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["github_token"] == "[REDACTED]"


def test_redact_text_does_not_mangle_normal_source_code():
    policy = SensitiveDataPolicy()
    source = (
        'token = os.getenv("TOKEN")\n'
        'api_key = config.get("api_key")\n'
        'password = input("Password: ")\n'
        'client_secret = None\n'
    )

    assert policy.redact_text(source) == source


def test_redact_text_redacts_json_by_sensitive_key():
    policy = SensitiveDataPolicy()

    result = policy.redact_text(
        '{"token":"fake-value","safe":"visible"}'
    )

    assert "fake-value" not in result
    assert "[REDACTED]" in result
    assert "visible" in result


def test_sensitive_environment_key_detection_is_shared_and_conservative():
    policy = SensitiveDataPolicy()

    assert policy.is_sensitive_env_key("OPENAI_API_KEY") is True
    assert policy.is_sensitive_env_key("GITHUB_TOKEN") is True
    assert policy.is_sensitive_env_key("HF_TOKEN") is True
    assert policy.is_sensitive_env_key("AWS_ACCESS_KEY_ID") is True
    assert policy.is_sensitive_env_key("AWS_SECRET_ACCESS_KEY") is True
    assert policy.is_sensitive_env_key("TOKENIZERS_PARALLELISM") is False
    assert policy.is_sensitive_env_key("PATH") is False
