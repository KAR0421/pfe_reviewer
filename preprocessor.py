def preprocess_script(script):
    lines = script.splitlines()
    cleaned = []

    for line in lines:
        line = line.strip()

        if not line:
            continue

        # remove comments (basic)
        if line.startswith("//"):
            continue

        cleaned.append(line)

    return cleaned