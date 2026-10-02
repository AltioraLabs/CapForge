"""SkillForge Typed Exceptions."""


class SkillForgeError(Exception):
    """Base class for all SkillForge exceptions."""
    pass


class CapabilityNotFoundError(SkillForgeError):
    """Raised when a requested capability or version is not found in the registry."""
    def __init__(self, capability_id: str, version: str | None = None):
        msg = f"Capability '{capability_id}'"
        if version:
            msg += f" with version '{version}'"
        msg += " was not found in the registry."
        super().__init__(msg)
        self.capability_id = capability_id
        self.version = version


class VerificationFailedError(SkillForgeError):
    """Raised when a candidate capability fails verification gates."""
    def __init__(self, capability_id: str, failed_tests: int, total_tests: int, details: str = ""):
        super().__init__(
            f"Verification failed for '{capability_id}': {failed_tests}/{total_tests} tests failed. {details}"
        )
        self.capability_id = capability_id
        self.failed_tests = failed_tests
        self.total_tests = total_tests


class RegressionDetectedError(SkillForgeError):
    """Raised when an updated capability breaks a previously passing test in the regression battery."""
    def __init__(self, capability_id: str, broken_version: str, test_id: str):
        super().__init__(
            f"Regression detected in '{capability_id}'! Version '{broken_version}' failed historical test '{test_id}'."
        )
        self.capability_id = capability_id
        self.broken_version = broken_version
        self.test_id = test_id


class SandboxExecutionError(SkillForgeError):
    """Raised when execution within the sandbox encounters a fatal error or timeout."""
    def __init__(self, message: str, exit_code: int | None = None, traceback: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.traceback = traceback
