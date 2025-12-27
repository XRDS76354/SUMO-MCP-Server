from pathlib import Path


def test_tests_import_local_src_packages() -> None:
    import mcp_tools

    repo_root = Path(__file__).resolve().parents[1]
    expected_src = (repo_root / "src").resolve()

    module_path = Path(mcp_tools.__file__).resolve()
    assert expected_src in module_path.parents

