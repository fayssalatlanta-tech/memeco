def require_keys(data: dict, required_keys: list[str], context: str = "data") -> None:
    missing = [key for key in required_keys if data.get(key) is None]

    if missing:
        raise ValueError(f"Missing required keys in {context}: {missing}")