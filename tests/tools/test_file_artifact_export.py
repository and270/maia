from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


def test_export_file_to_host_preserves_arbitrary_binary_bytes(tmp_path):
    source = tmp_path / "generated.bin"
    payload = (bytes(range(256)) * 600) + b"\x00\xfftail"
    source.write_bytes(payload)
    destination = tmp_path / "private" / "payload"

    env = LocalEnvironment(cwd=str(tmp_path), timeout=10)
    try:
        result = ShellFileOperations(env).export_file_to_host(
            "generated.bin",
            destination,
            max_bytes=1024 * 1024,
            chunk_bytes=64 * 1024,
        )
    finally:
        env.cleanup()

    assert result["success"] is True
    assert result["bytes"] == len(payload)
    assert destination.read_bytes() == payload


def test_export_file_to_host_enforces_limit_before_transfer(tmp_path):
    (tmp_path / "large.bin").write_bytes(b"x" * 1025)
    destination = tmp_path / "private" / "payload"

    env = LocalEnvironment(cwd=str(tmp_path), timeout=10)
    try:
        result = ShellFileOperations(env).export_file_to_host(
            "large.bin", destination, max_bytes=1024
        )
    finally:
        env.cleanup()

    assert result["success"] is False
    assert "exceeding the configured limit" in result["error"]
    assert not destination.exists()
