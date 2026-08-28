def clamp(value, lower, upper):
    """Clamp value to the inclusive interval [lower, upper]."""
    return min(lower, max(value, upper))
