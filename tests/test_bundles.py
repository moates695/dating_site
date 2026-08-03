import pytest

from app.bundles import BundleError, resolve_asset, resolve_bundle_dir

from conftest import TEST_TOKEN


def test_resolves_a_file_inside_the_bundle(bundle_dir):
    resolved = resolve_asset(bundle_dir, TEST_TOKEN, "style.css")
    assert resolved == (bundle_dir / TEST_TOKEN / "style.css").resolve()


def test_resolves_nested_bundle_dir(bundle_dir):
    (bundle_dir / TEST_TOKEN / "v1").mkdir()
    (bundle_dir / TEST_TOKEN / "v1" / "index.html").write_text("x", encoding="utf-8")
    assert resolve_asset(bundle_dir, f"{TEST_TOKEN}/v1", "index.html").is_file()


@pytest.mark.parametrize(
    "asset_path",
    [
        "../secret.txt",
        "../../etc/passwd",
        "sub/../../secret.txt",
        "/etc/passwd",
        "....//secret.txt",
    ],
)
def test_rejects_traversal(bundle_dir, asset_path):
    with pytest.raises(BundleError):
        resolve_asset(bundle_dir, TEST_TOKEN, asset_path)


def test_rejects_symlink_escaping_the_bundle(bundle_dir):
    link = bundle_dir / TEST_TOKEN / "escape.txt"
    link.symlink_to(bundle_dir / "secret.txt")
    with pytest.raises(BundleError):
        resolve_asset(bundle_dir, TEST_TOKEN, "escape.txt")


def test_rejects_missing_file(bundle_dir):
    with pytest.raises(BundleError):
        resolve_asset(bundle_dir, TEST_TOKEN, "nope.css")


def test_rejects_directory_as_asset(bundle_dir):
    (bundle_dir / TEST_TOKEN / "img").mkdir()
    with pytest.raises(BundleError):
        resolve_asset(bundle_dir, TEST_TOKEN, "img")


def test_bundle_dir_cannot_escape_pages_dir(bundle_dir):
    with pytest.raises(BundleError):
        resolve_bundle_dir(bundle_dir, "../elsewhere")
