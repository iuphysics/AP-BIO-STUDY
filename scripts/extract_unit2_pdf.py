"""Extract the AP Biology Unit 2 scoring guide into the site's question-bank format.

Usage: python scripts/extract_unit2_pdf.py /path/to/unit-2.pdf

The source PDF is read only. Images retain the original question wording,
figures, tables, and scoring material; correct-answer highlighting is removed
from the student-facing prompt and option crops.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import pymupdf as pdf
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "questions"
OUT.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument("pdf")
args = parser.parse_args()
source = pdf.open(args.pdf)
clean = pdf.open(args.pdf)
TOP, BOTTOM, LEFT, RIGHT = 60, 765, 36, 576

# The guide uses these pale-green/green paints for a keyed option. Make them
# white only in student-facing crops; explanation and rubric crops stay exact.
for page in clean:
    for xref in page.get_contents():
        stream = clean.xref_stream(xref)
        stream = re.sub(rb"\.902 1 \.902 (rg|RG)", rb"1 1 1 \1", stream)
        stream = re.sub(rb"\.2275 \.5686 \.2471 (rg|RG)", rb"1 1 1 \1", stream)
        clean.update_stream(xref, stream)

starts, option_markers = [], []
for page_index, page in enumerate(source):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                match = re.match(r"^\(([A-E])\)", span["text"].strip())
                if match and 55 < span["bbox"][0] < 90:
                    option_markers.append({"p": page_index, "y": span["bbox"][1], "letter": match[1]})
    for block in page.get_text("blocks"):
        match = re.match(r"^(\d+)\.\n", block[4])
        if match and block[0] < 50 and block[1] >= TOP:
            starts.append({"id": int(match[1]), "p": page_index, "y": block[1] - 3})

starts.sort(key=lambda item: item["id"])
expected = list(range(1, starts[-1]["id"] + 1))
if [item["id"] for item in starts] != expected:
    raise ValueError("Could not identify one ordered start for every question")

def key(item):
    return item["p"], item["y"]

def crop(start, end, prefix, *, original=False, left=LEFT, right=RIGHT):
    """Create lossless source crops spanning two document positions."""
    doc = source if original else clean
    result = []
    for page_index in range(start["p"], end["p"] + 1):
        y0 = start["y"] if page_index == start["p"] else TOP
        y1 = end["y"] if page_index == end["p"] else BOTTOM
        if y1 - y0 < 2:
            continue
        clip = pdf.Rect(left, y0, right, y1)
        pixmap = doc[page_index].get_pixmap(matrix=pdf.Matrix(1.0, 1.0), clip=clip, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        bbox = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
        if not bbox:
            continue
        image = image.crop((0, max(0, bbox[1] - 8), image.width, min(image.height, bbox[3] + 8)))
        name = f"{prefix}-p{page_index + 1}.webp"
        image.save(OUT / name, "WEBP", lossless=True)
        result.append({"src": f"assets/questions/{name}", "width": image.width, "height": image.height,
                       "page": page_index + 1, "text": doc[page_index].get_text("text", clip=clip).strip()})
    return result

questions, audit = [], []
for index, start in enumerate(starts):
    end = starts[index + 1] if index + 1 < len(starts) else {"p": len(source) - 1, "y": BOTTOM}
    all_options = [marker for marker in option_markers if key(start) <= key(marker) < key(end)]
    all_letters = "".join(marker["letter"] for marker in all_options)
    # Matching-set questions print a preliminary A-E key before their own
    # answer choices. The final complete sequence is the answer set.
    if all_letters.endswith("ABCDE"):
        options, letters = all_options[-5:], "ABCDE"
    elif all_letters.endswith("ABCD"):
        options, letters = all_options[-4:], "ABCD"
    else:
        options, letters = all_options, all_letters
    number = start["id"]
    if letters in ("ABCD", "ABCDE"):
        section_text = source[start["p"]].get_text("text") if start["p"] == end["p"] else ""
        answer_hits = []
        for page_index in range(start["p"], end["p"] + 1):
            y0 = start["y"] if page_index == start["p"] else TOP
            y1 = end["y"] if page_index == end["p"] else BOTTOM
            for block in source[page_index].get_text("blocks"):
                if block[1] >= y0 and block[1] < y1:
                    match = re.match(r"^Answer ([A-E])", block[4].strip())
                    if match:
                        answer_hits.append((match[1], {"p": page_index, "y": block[1] - 8}))
        if len(answer_hits) > 1:
            raise ValueError(f"Question {number}: found multiple written answers")
        # Some guide questions show only the highlighted keyed choice, without
        # repeating an "Answer X" line. Read that source highlight as a fallback.
        highlighted = []
        for option in options:
            for drawing in source[option["p"]].get_drawings():
                color = drawing.get("fill")
                rect = drawing["rect"]
                if (color and abs(color[0] - .902) < .002 and abs(color[1] - 1) < .002
                        and abs(color[2] - .902) < .002 and rect.x0 < 90
                        and abs(rect.y0 - option["y"]) < 2):
                    highlighted.append(option["letter"])
                    break
        if len(answer_hits) == 1:
            correct, answer_start = answer_hits[0]
            if highlighted and highlighted != [correct]:
                raise ValueError(f"Question {number}: written and highlighted answers disagree")
        elif len(highlighted) == 1:
            correct, answer_start = highlighted[0], end
        else:
            raise ValueError(f"Question {number}: no reliable answer key")
        question = {"id": number, "type": "mcq", "page": start["p"] + 1, "context": [],
                    "prompt": crop(start, {**options[0], "y": options[0]["y"] - 3}, f"q{number}-prompt"),
                    "options": [], "correct": correct,
                    "explanation": crop(answer_start, end, f"q{number}-explanation", original=True) if answer_hits else []}
        for option_index, option in enumerate(options):
            stop = options[option_index + 1] if option_index + 1 < len(options) else answer_start
            images = crop({**option, "y": option["y"] - 2}, {**stop, "y": stop["y"] - 2},
                          f"q{number}-{option['letter']}", left=68)
            text = " ".join(image["text"] for image in images).strip()
            text = re.sub(r"^\([A-E]\)\s*", "", text)
            question["options"].append({"letter": option["letter"], "text": text, "images": images,
                                        "graphical": not bool(text)})
        if not question["prompt"] or any(not option["images"] for option in question["options"]):
            raise ValueError(f"Question {number}: missing student-facing crop")
        audit.append({"id": number, "type": "mcq", "correct": correct, "options": len(options)})
    else:
        rubric_start = None
        for page_index in range(start["p"], end["p"] + 1):
            y0 = start["y"] if page_index == start["p"] else TOP
            y1 = end["y"] if page_index == end["p"] else BOTTOM
            for block in source[page_index].get_text("blocks"):
                rubric_heading = re.match(r"^(Part [A-D]|General)\b", block[4].strip())
                rubric_heading = rubric_heading or re.match(r"^Identification\s*&\s*Explanation\b", block[4].strip())
                if block[0] < 180 and y0 <= block[1] < y1 and rubric_heading:
                    rubric_start = {"p": page_index, "y": block[1] - 4}
                    break
            if rubric_start:
                break
        if not rubric_start:
            raise ValueError(f"Question {number}: could not locate scoring rubric")
        question = {"id": number, "type": "frq", "page": start["p"] + 1, "context": [],
                    "prompt": crop(start, rubric_start, f"q{number}-prompt"),
                    "rubric": crop(rubric_start, end, f"q{number}-rubric", original=True)}
        if not question["prompt"] or not question["rubric"]:
            raise ValueError(f"Question {number}: missing free-response crop")
        audit.append({"id": number, "type": "frq", "rubricPage": rubric_start["p"] + 1})
    questions.append(question)

data = {"title": "AP Biology Unit 2 Practice", "source": Path(args.pdf).name, "sourcePages": len(source),
        "sourceSha256": hashlib.sha256(Path(args.pdf).read_bytes()).hexdigest(), "sharedGroups": [], "questions": questions}
(ROOT / "questions.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
(ROOT / "scripts" / "extraction-audit.json").write_text(json.dumps(audit, indent=2) + "\n")
mcq_count = sum(question["type"] == "mcq" for question in questions)
print(f"Extracted {len(questions)} questions: {mcq_count} MCQs and {len(questions) - mcq_count} FRQs.")
