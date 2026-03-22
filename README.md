# DeepResearch DOCX to Markdown — Claude Code Skill

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that converts ChatGPT DeepResearch Word document exports (`.docx`) into clean, Obsidian-compatible Markdown.

## What it does

ChatGPT's DeepResearch feature produces well-structured research reports, but its `.docx` exports lose fidelity when converted with generic tools. This skill handles all the edge cases specific to DeepResearch exports:

- **Headings** detected via Word paragraph styles and font-size fallbacks
- **Code blocks** with language detection (Python, TypeScript, Bash, SQL, JSON, YAML, etc.) — preserves original indentation from `<w:br/>` line breaks
- **Mermaid diagrams** auto-detected and fenced, with special-character quoting for parentheses/braces in labels
- **Office MathML to LaTeX** — inline `$...$` and display `$$...$$`, with operator spacing, `\text{}` wrapping for prose in math, and accent/Greek letter support
- **Citation links** as `[N](url)` — resolved from the bibliography section at the end of the document
- **Tables** in GitHub-Flavored Markdown with escaped pipes and `<br>` for multi-line cells
- **Lists** — bullet, numbered, and alphabetical with proper nesting
- **Bold/italic** merging around math expressions (fixes DeepResearch's run-splitting artifacts)
- **Markdown escaping** for angle brackets in prose (without breaking code blocks)

## Installation

Copy the skill directory into your Claude Code skills folder, or reference it directly when invoking:

```
~/.claude/skills/deepresearch-docx-to-markdown/
  SKILL.md      # Skill prompt with full conversion instructions
  docx2md.py    # Python conversion script (~1550 lines)
```

The only external dependency is `python-docx`. When `uv` is available, the skill runs the script in an isolated environment via `uv run --with python-docx` — no global packages are modified. It falls back to `pip` otherwise:

```bash
# Preferred (isolated, no system pollution)
uv run --with python-docx python3 docx2md.py input.docx output.md

# Fallback
pip install python-docx
```

## Usage

In Claude Code, simply ask to convert a `.docx` file:

```
Convert this DeepResearch export to Markdown: /path/to/report.docx
```

Or invoke the skill explicitly:

```
Use the deepresearch-docx-to-markdown skill to convert /path/to/report.docx
```

The skill uses `context: fork` in its frontmatter, so Claude Code automatically runs it in an isolated sub-agent — keeping your main conversation context clean. For multiple files, Claude launches parallel sub-agents (one per file).

Each invocation will:
1. Run `docx2md.py` on the input file
2. Verify the output for common issues (broken LaTeX, unquoted Mermaid chars, citation format)
3. Report file stats: line count, number of citations, math blocks, code blocks, and any issues found

## Initial prompt

This skill was bootstrapped from a single natural-language prompt describing the desired conversion behavior:

> Convert this Word document to a Markdown file with the same content, make sure that all the links work! (Note: this Word document was exported by ChatGPT DeepResearch.)
>
> **Formatting requirements:**
> - All paragraphs properly separated
> - Lists properly converted (bullet, alphabetical, numbered)
> - Multiple code lines (e.g. Consolas font) converted to code blocks with correct language selection and original indentation
> - Inline mono-font words converted to `` `code` `` spans
> - Headline levels recognized (same font family, different sizes, e.g. Aptos)
> - Bold and other font styles detected
> - Tables, images, and all other formatting preserved
>
> **Mermaid diagrams:**
> Detect Mermaid diagrams that may start only with the diagram type (e.g. `sequenceDiagram`, `flowchart`). Round brackets `()` define stadium/rounded nodes in Mermaid, so they break edge and node labels when used literally — quote them.
>
> **Markdown escaping:**
> Properly escape characters like `<Name>` that would break rendering.
>
> **Citations / bibliography:**
> The document has a bibliography section at the end with numbered web links. The same numbers (e.g. `[1]`) appear inline with direct URLs. Convert these so they work in Obsidian — clicking a link must open the web page. `[[1]](url)` does **not** work (it navigates to a non-existent page "1"). Footnotes (`[^N]`) only render as clickable in Reading mode, not Live Preview. Use `[N](url)` instead — a small clickable number that opens the URL directly.
>
> **Math (LaTeX):**
> Convert inline and block-level math so Obsidian recognizes it as LaTeX. Pay special attention to variables with hats, Greek letters, upper/lower indices. Note that `%` can break rendering (e.g. `$CI_{95%}$`).

## How it works

The conversion pipeline has four components:

1. **`MathMLToLatex`** — Recursive converter from Office MathML (`<m:oMath>`) to LaTeX. Handles fractions, superscripts, subscripts, accents, matrices, and the `cases` environment.
2. **`DocxToMarkdown`** — Main converter. Opens the `.docx` with `python-docx`, resolves hyperlinks from the ZIP's relationship file, detects the bibliography section, then walks body elements producing Markdown line by line.
3. **Helper functions** — Hyperlink resolution, language guessing (regex heuristics for ~12 languages), Mermaid detection, Markdown escaping.
4. **Post-processor** — Cleans up bold-around-math artifacts via iterative regex, collapses blank lines, trims code-block language tags.

## Benchmarks

The `benchmarks/` directory contains two real-world ChatGPT DeepResearch exports alongside their converted Markdown output, demonstrating the skill's handling of complex formatting:

### LLM-as-a-Judge in Benchmarks for Coding Agents

| | Source (.docx) | Output (.md) |
|---|---|---|
| **File** | `LLM-as-a-Judge in Benchmarks for Coding‑Agents.docx` | `LLM-as-a-Judge in Benchmarks for Coding‑Agents.md` |
| **Language** | German (with English technical terms) |
| **Lines** | — | 359 |

A research report on using LLMs as judges in coding agent benchmarks. Exercises the converter's handling of:
- Dense LaTeX math (pass@k formulas, win-rate equations, confidence intervals, statistical tests)
- Display math with `cases` environment and piecewise definitions
- Citation links (35+ references to arXiv papers and conference proceedings)
- Complex GFM tables with multi-column comparisons
- Mermaid sequence diagrams with special characters in labels
- Mixed German/English prose with technical formatting

### AI Agents for Low-Code Tools

| | Source (.docx) | Output (.md) |
|---|---|---|
| **File** | `AI-Agenten for Low-Code-Tools.docx` | `AI-Agenten for Low-Code-Tools.md` |
| **Language** | German (with English technical terms) |
| **Lines** | — | 491 |

A research report on AI agents for model querying and modification in design, process, and low-code tools (Figma, Camunda, Salesforce, Mendix). Exercises the converter's handling of:
- Code blocks in multiple languages (bash, TypeScript, JSON, Python, XML)
- Mermaid sequence diagrams with complex interactions and quoting
- Large tables with vendor comparisons and API details
- Inline code mixed with bold text and citations
- 35+ citation links resolved from a bibliography section

## Project structure

```
deepresearch-docx-to-markdown-skill/
  SKILL.md                  # Claude Code skill definition
  docx2md.py                # Python conversion script
  README.md                 # This file
  benchmarks/
    *.docx                  # Original DeepResearch exports
    *.md                    # Converted Markdown output
```

## License

MIT
