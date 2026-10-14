def iter_statements(script: str) -> list[str]:
    """Делит SQL по `;`, не разрывая строки и dollar-quoted блоки."""
    parts: list[str] = []
    buf: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        if script.startswith("--", index):
            end = script.find("\n", index)
            index = length if end < 0 else end + 1
            continue
        char = script[index]
        if char == "'":
            buf.append(char)
            index += 1
            while index < length:
                buf.append(script[index])
                if script[index] == "'":
                    if index + 1 < length and script[index + 1] == "'":
                        buf.append(script[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "$":
            tag_end = index + 1
            while tag_end < length and (script[tag_end].isalnum() or script[tag_end] == "_"):
                tag_end += 1
            if tag_end < length and script[tag_end] == "$":
                tag = script[index : tag_end + 1]
                close = script.find(tag, tag_end + 1)
                if close < 0:
                    raise RuntimeError("незакрытый dollar-quote в SQL")
                buf.append(script[index : close + len(tag)])
                index = close + len(tag)
                continue
        if char == ";":
            statement = "".join(buf).strip()
            if statement:
                parts.append(statement)
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts
