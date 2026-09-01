class JarvisError(Exception):
    """Base exception for expected Jarvis failures."""


class ConfigurationError(JarvisError):
    pass


class ProviderError(JarvisError):
    def __init__(self, provider: str, operation: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.retryable = retryable


class StateTransitionError(JarvisError):
    pass


class ActionPolicyError(JarvisError):
    pass


class MemorySecurityError(JarvisError):
    pass


class AudioDeviceError(JarvisError):
    pass
