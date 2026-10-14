"""Lexical helpers: blank out comments and string contents without changing offsets.

Limitation: an apostrophe in JSX text (for example `don't`) starts a "string" and can hide
later code. The gate shows any resulting disagreement; it is not silently wrong.
"""


def _blank(chunk):
    return "".join("\n" if ch == "\n" else " " for ch in chunk)


def mask(src, hash_comments=False, blank_strings=True, apostrophe_in_words=False):
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "//" or (hash_comments and c == "#" and src[i + 1:i + 2] != "["):
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(_blank(src[i:j]))
            i = j
        elif c in "'\"`" and not (apostrophe_in_words and c == "'" and i > 0
                                  and src[i - 1].isalnum() and src[i + 1:i + 2].isalpha()):
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            j = min(j, n)
            body = src[i + 1:j]
            out.append(c + (_blank(body) if blank_strings else body) + (c if j < n else ""))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def match_brace(masked, start):
    depth = 0
    for i in range(start, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(masked) - 1
