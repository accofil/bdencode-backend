"""Release-kit primitives (NFO, description, MediaInfo, screenshots) and the dupe check.

Since 3.0 BDEncode creates no torrent and uploads nothing to a tracker.
"""

from .adapters import (
    AdapterConfigurationError,
    AdapterError,
    CredentialLoader,
    DupeChecker,
    DupeCheckOutcome,
    DupeCheckReceipt,
    HttpDupeChecker,
)
from .models import (
    PackageFile,
    PackageFileRole,
    ReleaseMetadata,
    ReleasePackageManifest,
    ReleasePreparationState,
    TrackerProfile,
)
from .names import ReleaseNameError, payload_path_for, validate_release_name
from .package import (
    UploadKitError,
    UploadKitResult,
    build_upload_kit,
    load_verified_upload_kit,
    sanitize_release_text,
    verify_upload_kit,
)


__all__ = [
    "AdapterConfigurationError",
    "AdapterError",
    "CredentialLoader",
    "DupeCheckOutcome",
    "DupeCheckReceipt",
    "DupeChecker",
    "HttpDupeChecker",
    "PackageFile",
    "PackageFileRole",
    "ReleaseMetadata",
    "ReleaseNameError",
    "ReleasePackageManifest",
    "ReleasePreparationState",
    "TrackerProfile",
    "UploadKitError",
    "UploadKitResult",
    "build_upload_kit",
    "load_verified_upload_kit",
    "payload_path_for",
    "sanitize_release_text",
    "validate_release_name",
    "verify_upload_kit",
]
