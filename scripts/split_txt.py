"""Chia file text thành N phần — 4 mode: line | section | file | ast.

Chay:
    python scripts/split_txt.py <file> --parts 5 --mode line
    python scripts/split_txt.py <file> --parts 5 --mode section
    python scripts/split_txt.py <file> --parts 5 --mode file
    python scripts/split_txt.py <file.py> --parts 5 --mode ast
"""
import argparse
import ast
import math
import re
import sys
from pathlib import Path


def split_line(content: str, n: int, src: Path) -> list[tuple[str, str]]:
    """Chia đều theo dòng — fallback an toàn nhất."""
    lines = content.splitlines(keepends=True)
    total = len(lines)
    chunk_size = math.ceil(total / n)
    parts = []
    for i in range(n):
        start = i * chunk_size
        end = min(start + chunk_size, total)
        if start >= total:
            break
        parts.append((
            f"{src.stem}_p{i+1}.txt",
            "".join(lines[start:end]),
        ))
    return parts


def split_section(content: str, n: int, src: Path) -> list[tuple[str, str]]:
    """Chia theo header SECTION/═══ — dùng cho packet_full.txt."""
    # Match: "═" x 72, dòng tiếp là "SECTION N — ...", rồi "═" x 72
    pattern = re.compile(r"(?m)^═{10,}\r?\n(SECTION \d+.*)\r?\n═{10,}")
    matches = list(pattern.finditer(content))
    if not matches:
        print("[!] Không tìm thấy header SECTION — fallback line", file=sys.stderr)
        return split_line(content, n, src)

    # Gom section vào N nhóm, cân bằng kích thước
    sections = []
    prev_end = 0
    for m in matches:
        if prev_end > 0:
            sections[-1] = (sections[-1][0], content[prev_end:m.start()])
        sections.append((m.group(1), ""))
        prev_end = m.start()
    sections[-1] = (sections[-1][0], content[prev_end:])

    total_chars = len(content)
    target = total_chars / n
    parts = []
    buf, buf_names, buf_size = [], [], 0
    for name, body in sections:
        buf.append(f"═══ {name} ═══\n{body}")
        buf_names.append(name.split("—")[0].strip()[:30])
        buf_size += len(body)
        if buf_size >= target and len(parts) < n - 1:
            parts.append((
                f"{src.stem}_p{len(parts)+1}_[{'|'.join(buf_names[:3])}].txt",
                "\n".join(buf),
            ))
            buf, buf_names, buf_size = [], [], 0
    if buf:
        parts.append((
            f"{src.stem}_p{len(parts)+1}_[{'|'.join(buf_names[:3])}].txt",
            "\n".join(buf),
        ))
    return parts


def split_file(content: str, n: int, src: Path) -> list[tuple[str, str]]:
    """Chia theo marker FILE / ### path — dùng cho bundle hoặc core_full.txt."""
    # Match "═══ FILE: path ═══" hoặc "### N. path/to/file.py"
    patterns = [
        re.compile(r"(?m)^[═=]{10,}\r?\nFILE: (.+?)\r?\n[═=]{10,}"),
        re.compile(r"(?m)^### \d+\. `([^`]+)`"),
    ]
    matches = []
    for pat in patterns:
        m = list(pat.finditer(content))
        if m and len(m) > 1:
            matches = m
            break

    if not matches:
        print("[!] Không tìm thấy marker FILE — fallback line", file=sys.stderr)
        return split_line(content, n, src)

    # Gom file vào N nhóm
    blocks = []
    prev_end = 0
    for m in matches:
        if prev_end > 0:
            blocks[-1] = (blocks[-1][0], content[prev_end:m.start()])
        blocks.append((m.group(1), ""))
        prev_end = m.start()
    blocks[-1] = (blocks[-1][0], content[prev_end:])

    total_chars = len(content)
    target = total_chars / n
    parts = []
    buf, buf_names, buf_size = [], [], 0
    for name, body in blocks:
        buf.append(body)
        buf_names.append(Path(name).name)
        buf_size += len(body)
        if buf_size >= target and len(parts) < n - 1:
            parts.append((
                f"{src.stem}_p{len(parts)+1}_{len(buf_names)}files.txt",
                "".join(buf),
            ))
            buf, buf_names, buf_size = [], [], 0
    if buf:
        parts.append((
            f"{src.stem}_p{len(parts)+1}_{len(buf_names)}files.txt",
            "".join(buf),
        ))
    return parts


def split_ast(content: str, n: int, src: Path) -> list[tuple[str, str]]:
    """Chia Python source — giữ nguyên hàm/class, không cắt giữa chừng."""
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"[!] SyntaxError: {e} — fallback line", file=sys.stderr)
        return split_line(content, n, src)

    lines = content.splitlines(keepends=True)

    # Tập dòng "an toàn" để cắt — ngay sau khi kết thúc top-level def/class
    cut_points = [0]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            cut_points.append(node.end_lineno)
    cut_points.append(len(lines))

    # Chia theo trọng số dòng
    total = len(lines)
    target = total / n
    parts = []
    start = 0
    for i in range(1, len(cut_points)):
        end = cut_points[i]
        if end - start >= target and len(parts) < n - 1:
            parts.append((
                f"{src.stem}_p{len(parts)+1}_L{start+1}-{end}.py",
                "".join(lines[start:end]),
            ))
            start = end
    if start < total:
        parts.append((
            f"{src.stem}_p{len(parts)+1}_L{start+1}-{total}.py",
            "".join(lines[start:]),
        ))
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--parts", "-n", type=int, default=5)
    ap.add_argument("--mode", choices=["line", "section", "file", "ast"],
                    default="line")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    if not args.file.exists():
        sys.exit(f"Khong tim thay: {args.file}")

    out_dir = args.out_dir or (args.file.parent / f"{args.file.stem}_split")
    out_dir.mkdir(parents=True, exist_ok=True)

    content = args.file.read_text(encoding="utf-8", errors="replace")
    splitter = {
        "line": split_line,
        "section": split_section,
        "file": split_file,
        "ast": split_ast,
    }[args.mode]

    parts = splitter(content, args.parts, args.file)

    print(f"[{args.mode}] {args.file} ({len(content)} chars) → {len(parts)} phần:")
    for name, body in parts:
        p = out_dir / name
        p.write_text(body, encoding="utf-8")
        print(f"  {name}  ({len(body):>7} chars, {body.count(chr(10))+1:>5} dòng)")


if __name__ == "__main__":
    main()