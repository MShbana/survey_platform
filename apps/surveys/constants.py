
from enum import Enum


class ValidationRuleKey(str, Enum):
    MIN = "min"
    MAX = "max"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    REGEX = "regex"


VALIDATION_RULE_KEYS = {key.value for key in ValidationRuleKey}
