"""Split the course Markdown into chunks for embedding.

Strategy (D017): a chunk never crosses a ## subtopic. Inside a subtopic, split at
### sections and pack neighbours together up to MAX_TOKENS. A section bigger than
MAX_TOKENS stays whole. Left out of the index (eval material): "In short",
learning objectives, "Check yourself".

Run from the repo root:
    python rag/chunker.py           # print a summary only
    python rag/chunker.py --write   # also save data/processed/chunks.jsonl (git-ignored)
"""

import argparse
import json
import re
import statistics
from pathlib import Path

import frontmatter

DATA_DIR = Path(__file__).parent.parent / "data" / "raw" / "tailabs"
OUT_FILE = Path(__file__).parent.parent / "data" / "processed" / "chunks.jsonl"
MAX_TOKENS = 800
EXCLUDE_MARKERS = ("By the end of this lesson you can", "**Check yourself**")


def estimate_tokens(text: str) -> int:
    return len(text) // 4  # rough: ~4 characters per token


def mark_code_lines(text: str) -> tuple[list[tuple[str, bool]], int, bool]:
    """Walk the Markdown line by line, tracking whether we are inside a code block.

    Returns (lines, blocks, unclosed):
      lines    - [(line, in_code), ...]; the fence lines themselves count as in_code
      blocks   - how many code blocks were opened
      unclosed - True if the file ends while still inside a code block
    A block opened with ```` only closes on a fence at least as long, so the
    ``` lines inside session 3's example README stay inside the outer block.
    """
    lines, blocks, fence = [], 0, None
    for line in text.splitlines():
        stripped = line.strip()
        if fence is None and re.match(r"^`{3,}", line):
            fence = re.match(r"^`{3,}", line).group()  # opening fence, e.g. ``` or ````
            blocks += 1
            lines.append((line, True))
        elif fence is not None:
            if re.fullmatch(r"`+", stripped) and len(stripped) >= len(fence):
                fence = None  # closing fence
            lines.append((line, True))
        else:
            lines.append((line, False))
    return lines, blocks, fence is not None


def split_sections(body: str) -> list[dict]:
    """Return [{"subtopic": ..., "section": ..., "text": ...}, ...] in file order."""
    sections = []
    current = None      # the section we're currently adding lines to (None = skip lines)
    excluding = False   # True while inside an objectives / Check yourself list

    for line, in_code in mark_code_lines(body)[0]:
        stripped = line.strip()

        if not in_code and line.startswith("## "):
            subtopic = line[3:]
            excluding = False
            if subtopic == "In short":
                current = None
            else:
                current = {"subtopic": subtopic, "section": "(intro)", "lines": []}
                sections.append(current)
        elif not in_code and line.startswith("### "):
            excluding = False
            if current is not None:
                current = {"subtopic": current["subtopic"], "section": line[4:], "lines": []}
                sections.append(current)
        elif not in_code and stripped.startswith(EXCLUDE_MARKERS):
            excluding = True          # drop the marker line itself

        elif excluding and (stripped == "" or stripped.startswith("- ")):
            continue                  # drop the bullets of that list

        else:
            excluding = False
            if current is not None:
                current["lines"].append(line)
    
    for section in sections:
        section["text"] = "\n".join(section.pop("lines")).strip()
    return [s for s in sections if s["text"]]


def heading_path(title: str, subtopic: str, section_names: list[str]) -> str:
    """'Title > Subtopic > Section A; Section B'. '(intro)' is left out of the path."""
    path = f"{title} > {subtopic}"
    named = [name for name in section_names if name != "(intro)"]
    if named:
        path += " > " + "; ".join(named)
    return path


def render(title: str, group: list[dict]) -> tuple[str, str]:
    """Return (heading_path, text) for a group, exactly as the chunk will be embedded.

    Used by pack() to measure size AND by chunk_file() to build the chunk,
    so the size that was checked is the size that gets embedded.
    """
    hp = heading_path(title, group[0]["subtopic"], [s["section"] for s in group])
    # Put each "### name" back above its text, so joined sections keep their sub-headings
    body = "\n\n".join(
        s["text"] if s["section"] == "(intro)" else f"### {s['section']}\n\n{s['text']}"
        for s in group
    )
    return hp, f"{hp}\n\n{body}"              # the heading path is embedded too


def pack(sections: list[dict], max_tokens: int | None = MAX_TOKENS, title: str = "") -> list[list[dict]]:
    """Group neighbouring sections of the SAME subtopic, up to max_tokens per group.

    Size is measured on the final chunk text (heading path + ### lines included).
    max_tokens=None -> one group per subtopic (the "## only" baseline).
    A section already bigger than max_tokens becomes a group of its own (never cut).
    """
    groups = []
    for section in sections:
        if groups:
            last = groups[-1]   # the box we're currently filling
            same_subtopic = last[-1]["subtopic"] == section["subtopic"]
            size = estimate_tokens(render(title, last + [section])[1])  # size IF we add it
            fits = max_tokens is None or size <= max_tokens
            if same_subtopic and fits:
                last.append(section)
                continue        # done with this section; go to the next one
        groups.append([section])   # start a new box containing just this section
    return groups


def chunk_file(path: Path, max_tokens: int | None = MAX_TOKENS) -> list[dict]:
    """Turn one lesson file into chunk dicts, ready to embed."""
    post = frontmatter.load(path)
    chunks = []
    groups = pack(split_sections(post.content), max_tokens, title=post["title"])
    for n, group in enumerate(groups, start=1):
        names = [s["section"] for s in group]
        subtopic = group[0]["subtopic"]          # pack() guarantees one subtopic per group
        hp, text = render(post["title"], group)

        chunks.append({
            "chunk_id": f"s{post['session']:02d}-c{n:03d}",   # e.g. s01-c003
            "session": post["session"],
            "title": post["title"],
            "url": post["url"],
            "subtopic": subtopic,
            "sections": names,
            "heading_path": hp,
            "text": text,
            "tokens_est": estimate_tokens(text),
        })
    return chunks


def chunk_all(max_tokens: int | None = MAX_TOKENS) -> list[dict]:
    """Chunk every lesson file, in session order."""
    chunks = []
    for path in sorted(DATA_DIR.glob("s*.md")):
        chunks.extend(chunk_file(path, max_tokens))
    return chunks


def write_jsonl(chunks: list[dict], out_file: Path) -> None:
    """Save chunks one per line. Overwritten on every run: it's derived data, rebuilt from the .md files."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk the course files and print a summary.")
    parser.add_argument("--write", action="store_true", help=f"also save the chunks to {OUT_FILE}")
    args = parser.parse_args()

    chunks = chunk_all()
    sizes = [c["tokens_est"] for c in chunks]
    print(f"{len(chunks)} chunks | median {int(statistics.median(sizes))} tokens | "
          f"max {max(sizes)} | over {MAX_TOKENS}: {sum(s > MAX_TOKENS for s in sizes)}")

    if args.write:
        write_jsonl(chunks, OUT_FILE)
        print(f"Wrote {len(chunks)} chunks -> {OUT_FILE}")
    else:
        print("(not saved; add --write to save them)")


if __name__ == "__main__":
    main()
