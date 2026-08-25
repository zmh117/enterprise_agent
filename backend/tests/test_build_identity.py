from __future__ import annotations

import pytest

from app.shared.build_identity import (
    BuildIdentity,
    BuildIdentityError,
    build_identity_from_environment,
)


def test_build_identities_compare_release_across_platform_specific_digests() -> None:
    arm = BuildIdentity(
        component="python-runtime",
        source_revision="revision-123",
        build_id="release-456",
        platform="linux/arm64",
        image_digest=f"sha256:{'a' * 64}",
    )
    amd = BuildIdentity(
        component="file-service",
        source_revision="revision-123",
        build_id="release-456",
        platform="linux/amd64",
        image_digest=f"sha256:{'b' * 64}",
    )

    assert (arm.source_revision, arm.build_id) == (
        amd.source_revision,
        amd.build_id,
    )
    assert arm.platform != amd.platform
    assert arm.image_digest != amd.image_digest


@pytest.mark.parametrize(
    "value",
    [
        {
            "component": "python-runtime",
            "source_revision": "",
            "build_id": "build-1",
            "platform": "linux/amd64",
        },
        {
            "component": "python-runtime",
            "source_revision": "revision-1",
            "build_id": "build-1",
            "platform": "amd64",
        },
        {
            "component": "python-runtime",
            "source_revision": "revision-1",
            "build_id": "build-1",
            "platform": "linux/amd64",
            "image_digest": "latest",
        },
        {
            "component": "control-plane",
            "source_revision": "revision-1",
            "build_id": "build-1",
            "platform": "linux/amd64",
        },
    ],
)
def test_build_identity_rejects_missing_illegal_tag_and_component_override(
    value: dict[str, str],
) -> None:
    with pytest.raises(BuildIdentityError):
        BuildIdentity.from_dict(value, expected_component="python-runtime")


def test_build_identity_environment_requires_complete_safe_release_manifest() -> None:
    with pytest.raises(BuildIdentityError):
        build_identity_from_environment(
            "agent-worker",
            {
                "BUILD_SOURCE_REVISION": "revision-1",
                "BUILD_ID": "build-1",
            },
        )

    identity = build_identity_from_environment(
        "agent-worker",
        {
            "BUILD_SOURCE_REVISION": "revision-1",
            "BUILD_ID": "build-1",
            "BUILD_PLATFORM": "linux/amd64",
            "BUILD_IMAGE_DIGEST": f"sha256:{'c' * 64}",
            "UNRELATED_SECRET": "must-not-project",
        },
    )

    assert identity.to_dict() == {
        "component": "agent-worker",
        "source_revision": "revision-1",
        "build_id": "build-1",
        "platform": "linux/amd64",
        "image_digest": f"sha256:{'c' * 64}",
    }
    assert "must-not-project" not in str(identity.to_dict())
