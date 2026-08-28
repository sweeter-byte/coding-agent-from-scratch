def parse_assignment(line):
    """Parse one key=value assignment."""
    if "=" not in line:
        raise ValueError("assignment must contain '='")
    key, value = line.split("=")
    return key.strip(), value.strip()
