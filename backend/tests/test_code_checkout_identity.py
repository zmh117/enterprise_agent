import os

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure import code_checkout_identity as identities


@pytest.fixture
def working(tmp_path):
    directory = tmp_path / "working"
    (directory / ".svn").mkdir(parents=True)
    return directory


def test_durable_identity_survives_remount_but_active_reader_does_not(working, monkeypatch):
    key = identities.persistent_identity(working, create=True)
    active = identities.CheckoutIdentity(working, key)
    old = identities.local_identity
    monkeypatch.setattr(
        identities, "local_identity", lambda path: (old(path)[0] + 1, old(path)[1] + 7)
    )
    identities.CheckoutIdentity(working, key).check()
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_IDENTITY_CHANGED"):
        active.check()


def test_missing_or_replaced_marker_is_rejected(working):
    key = identities.persistent_identity(working, create=True)
    active = identities.CheckoutIdentity(working, key)
    marker = working / ".svn" / identities.MARKER
    marker.unlink()
    with pytest.raises(CodeKnowledgeError):
        active.check()
    identities.persistent_identity(working, create=True)
    with pytest.raises(CodeKnowledgeError):
        identities.CheckoutIdentity(working, key)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory"])
def test_marker_cannot_be_an_alias_or_special_file(working, tmp_path, kind):
    key = identities.persistent_identity(working, create=True)
    marker = working / ".svn" / identities.MARKER
    if kind == "hardlink":
        os.link(marker, tmp_path / "alias")
    else:
        marker.unlink()
        if kind == "directory":
            marker.mkdir()
        else:
            target = tmp_path / "marker"
            target.write_text(key)
            marker.symlink_to(target)
    with pytest.raises(CodeKnowledgeError):
        identities.CheckoutIdentity(working, key)


def test_creation_is_idempotent_and_rejects_metadata_symlink(working, tmp_path):
    key = identities.persistent_identity(working, create=True)
    assert identities.persistent_identity(working, create=True) == key
    (working / ".svn").rename(tmp_path / "metadata")
    (working / ".svn").symlink_to(tmp_path / "metadata", target_is_directory=True)
    with pytest.raises(CodeKnowledgeError):
        identities.CheckoutIdentity(working, key)


def test_identity_marker_is_group_readable_even_under_private_umask(working):
    previous = os.umask(0o077)
    try:
        identities.persistent_identity(working, create=True)
    finally:
        os.umask(previous)
    assert (working / ".svn" / identities.MARKER).stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("denied", ["root", ".svn", identities.MARKER])
def test_permission_failure_does_not_claim_identity_changed(working, monkeypatch, denied):
    identities.persistent_identity(working, create=True)
    original = os.open

    def guarded(path, *args, **kwargs):
        if path == (working if denied == "root" else denied):
            raise PermissionError("synthetic protected path")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    with pytest.raises(CodeKnowledgeError, match="^CODE_CHECKOUT_PERMISSION_DENIED$"):
        identities.persistent_identity(working)
