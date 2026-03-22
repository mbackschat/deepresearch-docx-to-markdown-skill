---
name: deepresearch-docx-to-markdown
description: "Convert ChatGPT DeepResearch Word document exports (.docx) to Obsidian-compatible Markdown. Handles headings, bold/italic, inline code, code blocks with language detection, tables, Mermaid diagrams (with special-char quoting), Office MathML→LaTeX (with operator spacing and \\text{} wrapping), citation links as [N](url), and proper Markdown escaping."
context: fork
---

# DOCX → Markdown Converter (ChatGPT DeepResearch)

You are converting a Word document (.docx) exported by ChatGPT DeepResearch into an Obsidian-compatible Markdown file. Follow these steps carefully.

## 1. Check for bundled conversion script

This skill bundles a Python conversion script `docx2md.py` in the same directory as this SKILL.md file. Locate the skill directory (the folder containing this file) and check the script exists:

```bash
ls "<SKILL_DIR>/docx2md.py"
```

Where `<SKILL_DIR>` is the directory containing this SKILL.md (resolve it from the skill's location, e.g. using the path shown in the skill invocation).

If the script exists, attempt to run it. If it fails (e.g. missing dependency, Python version issue), recreate it from the specifications in the review sections below. The script requires only `python-docx` and standard library modules (`zipfile`, `xml.etree.ElementTree`, `re`, `pathlib`, `os`, `sys`).

**Install python-docx if missing:**
```bash
pip install python-docx --break-system-packages 2>/dev/null || pip install python-docx
```

## 2. Run the conversion

```bash
python3 "<SKILL_DIR>/docx2md.py" "<INPUT_DOCX>" "<OUTPUT_MD>"
```

Where `<INPUT_DOCX>` is the path to the uploaded .docx file and `<OUTPUT_MD>` is the desired output path (typically in `/sessions/*/mnt/outputs/`).

**Error handling:** If the script exits with a non-zero status, check stderr for the error message. Common failures:
- `ModuleNotFoundError: No module named 'docx'` → install python-docx (see step 1).
- `Error: Not a valid .docx file (bad ZIP)` → the file is corrupted or not a real .docx.
- `Error: File not found` → check the input path.

If the script crashes or produces garbled output, you may need to inspect the .docx XML directly (unzip it and examine `word/document.xml`) and fix the script's handling of the problematic element, or fall back to manual conversion using the review checklist below.

## 2b. Rebuilding the script — architecture and Word XML gotchas

If the bundled `docx2md.py` is missing or broken beyond repair, recreate it following this architecture and the detailed review checklist in section 3. The script is ~1550 lines of Python, built on `python-docx` plus raw XML access via `zipfile` + `xml.etree.ElementTree`.

### Overall architecture

The script has four main components:

1. **`MathMLToLatex` class** — Recursive converter from Office MathML (`<m:oMath>`, `<m:oMathPara>`) to LaTeX. Walks the OMML element tree with handler methods per tag (`_handle_f` for fractions, `_handle_sSup` for superscripts, etc.). Property elements (`*Pr`) are skipped. Has lookup tables for Greek letters, operators, and accent characters.
2. **`DocxToMarkdown` class** — Main converter. Opens the .docx with `python-docx`, resolves hyperlinks from the ZIP's relationship file, detects the bibliography section, then walks `body` elements producing Markdown line by line. Groups consecutive code paragraphs and list items together.
3. **Helper functions** — `resolve_hyperlinks()` (reads `word/_rels/document.xml.rels`), `guess_language()` (regex heuristics for ~12 languages), `is_mermaid_start()`, `escape_md()`, `escape_table_cell()`.
4. **Post-processor** (in `save()`) — Cleans up bold-around-math artifacts (`**text**** **$N$**` → `**text $N$ more**`) via iterative regex, collapses excessive blank lines, trims code-block language tags.

### Key Word XML patterns you must handle

These are the make-or-break details when working with `.docx` XML:

- **Line breaks inside code**: DeepResearch puts entire code blocks in ONE `<w:p>` paragraph. Individual lines are separated by `<w:br/>` elements *inside* `<w:r>` runs — NOT separate paragraphs. You must iterate `<w:r>` children in order (not just collect `<w:t>` text) to capture `<w:br/>` as `\n` and `<w:tab>` as `\t`. This is critical for **preserving original indentation**.
- **Code detection — style names vs. fonts**: Primary detection is the `SourceCode` paragraph style (`<w:pStyle w:val="SourceCode"/>`) and `VerbatimChar` run style. But also fall back to checking `<w:rFonts>` attributes (`w:ascii`, `w:hAnsi`, `w:cs`) for monospace fonts: Consolas, Courier New, Source Code Pro, Fira Code, JetBrains Mono, Cascadia Code, Roboto Mono, Menlo, Monaco. Any run in a mono font that's not inside a heading is likely inline code.
- **Inline code** (`\`text\``): Individual runs in mono font within a normal paragraph → wrap in backticks. Don't escape Markdown inside backticks. If the entire paragraph is code-styled, it's a code block, not inline code.
- **Lists — `numPr`**: List items are paragraphs with `<w:numPr>` inside `<w:pPr>`. The `<w:ilvl>` value (0-based) gives nesting depth, `<w:numId>` groups items under the same list. Bullet vs. numbered vs. alphabetical (`a)`, `b)`) must be inferred — check if the paragraph text itself starts with a number or letter pattern (DeepResearch bakes the label into the text), or inspect `<w:abstractNum>` in `numbering.xml` for the format pattern.
- **Heading detection**: Named styles `Heading1`–`Heading4` (regex: `/[Hh]eading\s*(\d+)/`). As a fallback, detect by font: same font family (Aptos) at different sizes → H1=20pt, H2=16pt, H3=14pt. Font size is in `<w:sz>` (half-points, so 40 = 20pt).
- **Hyperlinks**: `<w:hyperlink r:id="rIdN">` contains runs with display text. Resolve `rIdN` → URL from `word/_rels/document.xml.rels` (`<Relationship>` elements with `Type` containing "hyperlink").
- **Math**: `<m:oMath>` = inline math, `<m:oMathPara>` = display math. The `<m:nor/>` flag in run properties means "normal text" (upright) — wrap multi-word content in `\text{}`. Without this, each letter renders as a separate italic variable. Accent marks use `<m:acc>` with `<m:chr m:val="..."/>` for the combining character (e.g. U+0302 = hat). The `%` character must become `\%` inside math — unescaped `%` starts a LaTeX comment and breaks rendering.
- **Tables**: `<w:tbl>` → `<w:tr>` → `<w:tc>` → `<w:p>`. Render as GFM tables. Pipe chars in content must be `\|`. Multi-paragraph cells join with `<br>`.
- **Bibliography**: DeepResearch appends a bibliography at document end. Detect it by scanning backwards from the last paragraph: lines matching `[N] [M] ... URL` or pure URL lines. Build a `{citation_number → URL}` map. Suppress the bibliography from output. Use this map as the canonical URL source for `[N](url)` links in the body.
- **Images** (rare): If present, they're in `<w:drawing>` → `<wp:inline>` → `<a:blip r:embed="rIdN"/>`. Extract the image from the ZIP (`word/media/...`) and link with `![alt](path)`.

### Gotchas that are easy to get wrong

- **LaTeX operator spacing**: After translating Unicode operators to backslash commands (`\neg`, `\geq`, `\wedge`, `\sum` …), you MUST append a trailing space. Without it, `\neg T` becomes `\negT` which LaTeX doesn't understand. Single-symbol operators (`+`, `-`, `|`) don't need the space.
- **Bold merging around math**: DeepResearch splits bold runs around inline `<m:oMath>`, producing `**A** $X$ **B**`. The post-processor must iteratively merge these into `**A $X$ B**`. This needs multiple passes (≤5) because patterns nest.
- **`<w:br/>` vs. paragraph breaks**: In code blocks, `<w:br/>` = newline within the same paragraph (same code block). A new `<w:p>` = a new code block paragraph (join with extra newline). Getting this wrong mangles code indentation.
- **Mermaid parentheses**: `()` in Mermaid defines a stadium/rounded node shape, so literal parentheses in labels MUST be quoted. `[A (test)]` → `["A (test)"]`. Same for `{}` (diamond) and edge labels. Use regex to detect and auto-quote.
- **Citation link format**: ONLY use `[N](url)`. The alternatives all break in Obsidian: `[^N]` footnotes only render in Reading mode (not Live Preview, which is the default), `<sup>` HTML is not rendered, `[[N]](url)` creates a broken wikilink to page "N".
- **Angle bracket escaping**: `<Name>` in prose renders as (broken) HTML. Escape as `\<Name>`. But do NOT escape inside code blocks or backtick spans.
- **Paragraph separation**: Ensure every paragraph gets its own blank line before it in the output. Without this, Markdown renderers merge consecutive lines into one paragraph. Headings need a blank line both before and after.

## 3. Post-conversion review and fixes

After the automated conversion, **always review the output** and fix these common issues. Try really hard to get the formatting right — lists, code, tables, images, headings, and math all deserve careful attention:

### 3a. Code blocks and inline code
- ChatGPT DeepResearch exports code as single paragraphs with `<w:br/>` internal line breaks, using the `SourceCode` paragraph style and `VerbatimChar` run style.
- **Indentation is critical**: verify code blocks preserve the original indentation (spaces/tabs). DeepResearch uses `<w:tab/>` and literal spaces in `<w:t xml:space="preserve">`. Stripping leading whitespace destroys Python, YAML, and nested code.
- Check language detection: the script guesses based on content (Python, TypeScript, JavaScript, bash, SQL, JSON, YAML, XML, C++, Rust, Go, etc.). Correct if wrong.
- If a code block is actually Mermaid, ensure it uses ` ```mermaid `.
- **Inline code**: Words in monospace font (e.g. Consolas) within normal prose paragraphs must be converted to Markdown backtick code spans (`` `word` ``). Don't confuse a single inline-code run with a full code block — if the whole paragraph is code-styled, it's a block.

### 3b. Mermaid diagrams
- Detect diagrams starting with: `sequenceDiagram`, `flowchart`, `graph`, `classDiagram`, `stateDiagram`, `erDiagram`, `gantt`, `pie`, `gitgraph`, `journey`, `mindmap`, `timeline`.
- These may be in `SourceCode`-styled paragraphs or plain text. Wrap in ` ```mermaid ` fences.
- **Special characters in labels**: Mermaid reserves `()` for rounded nodes and `{}` for diamond nodes. Literal parentheses or braces inside node labels must be quoted: `[label]` → `["label"]`. Edge labels with parentheses also need quoting: `-- Win-Rate (Judge) -->` → `-- "Win-Rate (Judge)" -->`. The script handles this automatically, but verify after conversion.

### 3c. Math (LaTeX)
- Office MathML is converted to LaTeX. Verify:
  - **Hat/accent variables**: `\hat{P}`, `\hat{W}`, `\hat{M}` etc. — check they match the original.
  - **Greek letters**: α→`\alpha`, β→`\beta`, etc.
  - **Percent signs**: must be escaped as `\%` inside math, e.g. `$CI_{95\%}$`.
  - **Cases environment**: `\begin{cases}...\end{cases}` for piecewise definitions (Word uses matrix with `plcHide=on` inside `{` delimiters).
  - **Operator spacing**: LaTeX command-style operators (`\neg`, `\geq`, `\leq`, `\wedge`, `\sum`, `\prod`, etc.) need a trailing space before the next token, otherwise they merge with adjacent text (e.g. `\negT` instead of `\neg T`). The script handles this, but verify rendered output.
  - **Normal text in math** (`\text{}`): When Word marks math runs with `<m:nor/>` (normal/upright style), multi-word prose like "patch applies" must be wrapped in `\text{patch applies}` — otherwise each letter renders as a separate italic variable. The script detects `<m:nor/>` and wraps accordingly.
  - **Display math**: should be `$$...$$` on its own line.
  - **Inline math**: should be `$...$` within text.

### 3d. Bold/italic around math
- ChatGPT DeepResearch frequently interleaves bold text runs with inline math elements, producing artifacts like `**text**** **$N$** ****more**`.
- The script's post-processor merges these, but verify the result reads naturally, e.g.: `**text $N$ more**`.

### 3e. Hyperlinks and citations
- Citation-style links `[1]`, `[2]` etc. → plain inline links: `[N](url)`.
  In Obsidian this renders "N" as a small clickable number that opens the URL directly.
- **Do NOT use**: `[^N]` (footnotes — only work in Reading mode), `<sup>[N](url)</sup>` (HTML not rendered in Obsidian), or `[[N]](url)` (broken wikilink).
- The URL for each citation is resolved from the bibliography section (canonical) or from the hyperlink relationship.
- Regular hyperlinks → `[display text](url)`.

### 3f. Tables
- Verify GitHub-flavoured Markdown table syntax: header row, separator `|---|`, data rows.
- Pipe characters in cell content must be escaped: `\|`.
- Newlines in cells → `<br>`.

### 3g. Lists (bullet, numbered, and alphabetical)
- Word list items (`numPr`) → Markdown bullets (`- `), numbered lists (`1. `), or alphabetical lists (`a)`, `b)`).
- Nesting via indentation (`  - ` for level 1, `    - ` for level 2, etc.). The `<w:ilvl>` value gives nesting depth.
- Alphabetical lists (`a)`, `b)`, `c)` …) are exported by DeepResearch with the letter prefix baked into the paragraph text. Preserve these as-is; they render fine in Markdown.
- Inline lists within paragraphs (separated by `<w:br/>`) should appear on separate lines.
- Make sure all list types are properly separated from surrounding paragraphs (blank line before and after the list block).

### 3h. Heading levels
- Primary detection: paragraph style names `Heading1`–`Heading4` (regex match is case-insensitive).
- **Fallback — same font, different sizes**: If style names are missing, detect headings by font size. DeepResearch uses the same font family (Aptos / Aptos Display) at different sizes: H1=20pt (`<w:sz w:val="40"/>`), H2=16pt (32), H3=14pt (28). The `<w:sz>` value is in half-points.
- Heading 4+ → `#### ` etc.
- Ensure a blank line before and after every heading.

### 3i. Markdown escaping
- Angle brackets `<Name>` in prose must be escaped: `\<Name>` — otherwise they render as (broken) HTML tags and can swallow the following text entirely.
- Do NOT escape angle brackets inside code blocks or code spans.
- Be selective: only escape `<` that doesn't introduce a known HTML element (the script allowlists tags like `<br>`, `<a>`, `<code>`, etc.).

### 3j. Images
- DeepResearch exports are typically text-only, but if images are present they appear as `<w:drawing>` elements containing `<a:blip r:embed="rIdN"/>`.
- Extract the image file from the ZIP archive (`word/media/imageN.png` etc.) and save alongside the Markdown.
- Reference with `![alt text](imageN.png)` in the output.

### 3k. Bold and Italic
- `<w:b/>` or `<w:bCs/>` in run properties → `**text**`
- `<w:i/>` or `<w:iCs/>` in run properties → `*text*`
- Both → `***text***`
- `SourceCode` / `VerbatimChar` character style → `` `text` `` (inline code)

## 4. ChatGPT DeepResearch-specific assumptions

These assumptions are safe for documents exported by ChatGPT DeepResearch:

1. **Code detection**: Primarily via `SourceCode` paragraph style + `VerbatimChar` run style (case-insensitive matching). The script also falls back to detecting monospace fonts (Consolas, Courier New, Source Code Pro, etc.) for broader compatibility, though ChatGPT DeepResearch exports typically use named styles only.
2. **No Word footnotes/endnotes**: Links are stored as hyperlinks in `word/_rels/document.xml.rels`, not as Word footnotes.
3. **Bibliography section at end**: DeepResearch appends a bibliography that groups citation numbers by URL (e.g. `[1] [10] [24] https://...` or `[12] [22] Title\nhttps://...`). The converter detects this section, suppresses it from output, and uses it as the canonical URL source for inline `[N](url)` citation links. This avoids duplicates.
4. **Citation pattern**: Links display as `[1]`, `[2]` etc. and link to academic papers or documentation URLs.
5. **Single-paragraph code**: Each code "block" is typically ONE paragraph with internal `<w:br/>` line breaks, not multiple paragraphs.
6. **Theme fonts**: Aptos Display (headings) + Aptos (body). Heading sizes: H1=20pt, H2=16pt, H3=14pt.
7. **No images** (typical): DeepResearch exports are text-heavy with no embedded images.
8. **German + English mix**: Documents may contain German prose with English technical terms.

## 5. Final output

- Save the Markdown file to the outputs folder.
- Present it to the user with a `computer://` link.
- Mention any issues found during review that couldn't be auto-fix.
