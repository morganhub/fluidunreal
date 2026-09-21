"""The one exception the runtime raises, carrying a domain code the engine understands."""


class OpError(Exception):
    def __init__(self, code, message, recovery=None, details=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.recovery = recovery
        self.details = details or {}

    def as_record(self):
        return {
            "code": self.code,
            "message": self.message,
            "recovery": self.recovery,
            "details": self.details,
        }
