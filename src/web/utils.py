"""
Shared utility functions for the review web application.
"""

from flask import flash


def _validate_positive_int(
    param_name: str,
    value: int | None,
    default: int | None,
    min_value: int = 1,
    max_value: int | None = None,
    flash_errors: bool = True,
) -> int | None:
    """
    Validate and sanitize a positive integer query parameter.

    Args:
        param_name: Name of the parameter (for error messages)
        value: The value to validate
        default: Default value on validation failure
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        flash_errors: Whether to flash validation errors

    Returns:
        Validated integer or default
    """
    if value is None:
        return default

    if value < min_value:
        if flash_errors:
            flash(
                f"Invalid {param_name}: must be at least {min_value}. Using default: {default}",
                "warning",
            )
        return default

    if max_value is not None and value > max_value:
        if flash_errors:
            flash(
                f"Invalid {param_name}: must be at most {max_value}. Using {max_value}.",
                "warning",
            )
        return max_value

    return value
