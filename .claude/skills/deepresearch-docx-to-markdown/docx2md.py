#!/usr/bin/env python3
"""
docx2md.py – Convert ChatGPT DeepResearch DOCX exports to Obsidian-compatible Markdown.

Features:
  - Heading detection via paragraph styles (Heading 1/2/3/4)
  - Bold / Italic detection from run properties
  - Inline code detection via "Source Code" / "SourceCode" character style
  - Multi-line code block detection (consecutive SourceCode paragraphs)
  - Language guessing for code blocks
  - Table conversion to GitHub-flavoured Markdown tables
  - Bullet and numbered list conversion (with nesting)
  - Mermaid diagram detection (sequenceDiagram, flowchart, graph, etc.)
  - Hyperlink resolution from relationships
  - Citation-style link collection as Obsidian-compatible footnotes
  - Office MathML → LaTeX conversion (inline $…$ and block $$…$$)
  - Proper Markdown escaping for < > & in prose (but not in code/math)
  - Image extraction (if present)
"""

import sys
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn

# ── XML namespaces ──────────────────────────────────────────────────────────
NS = {
    'w':  'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r':  'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'm':  'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'a':  'http://schemas.openxmlformats.org/drawingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}


# ═══════════════════════════════════════════════════════════════════════════
#  MATH ML → LATEX CONVERTER
# ═══════════════════════════════════════════════════════════════════════════

class MathMLToLatex:
    """Convert Office MathML (OMML) elements to LaTeX strings."""

    # Map of accent characters to LaTeX commands
    ACCENT_MAP = {
        '\u0302': r'\hat',      # circumflex (hat)
        '\u0303': r'\tilde',    # tilde
        '\u0304': r'\bar',      # macron (bar)
        '\u0307': r'\dot',      # dot above
        '\u0308': r'\ddot',     # diaeresis (double dot)
        '\u20D7': r'\vec',      # vector arrow
        '\u0305': r'\overline', # overline
        '\u23DE': r'\overbrace',
        '\u23DF': r'\underbrace',
    }

    # Greek letter map
    GREEK_MAP = {
        'α': r'\alpha', 'β': r'\beta', 'γ': r'\gamma', 'δ': r'\delta',
        'ε': r'\epsilon', 'ζ': r'\zeta', 'η': r'\eta', 'θ': r'\theta',
        'ι': r'\iota', 'κ': r'\kappa', 'λ': r'\lambda', 'μ': r'\mu',
        'ν': r'\nu', 'ξ': r'\xi', 'π': r'\pi', 'ρ': r'\rho',
        'σ': r'\sigma', 'τ': r'\tau', 'υ': r'\upsilon', 'φ': r'\varphi',
        'χ': r'\chi', 'ψ': r'\psi', 'ω': r'\omega',
        'Α': r'\Alpha', 'Β': r'\Beta', 'Γ': r'\Gamma', 'Δ': r'\Delta',
        'Ε': r'\Epsilon', 'Ζ': r'\Zeta', 'Η': r'\Eta', 'Θ': r'\Theta',
        'Ι': r'\Iota', 'Κ': r'\Kappa', 'Λ': r'\Lambda', 'Μ': r'\Mu',
        'Ν': r'\Nu', 'Ξ': r'\Xi', 'Π': r'\Pi', 'Ρ': r'\Rho',
        'Σ': r'\Sigma', 'Τ': r'\Tau', 'Υ': r'\Upsilon', 'Φ': r'\Phi',
        'Χ': r'\Chi', 'Ψ': r'\Psi', 'Ω': r'\Omega',
        'ϕ': r'\phi', 'ϑ': r'\vartheta', 'ϵ': r'\varepsilon',
        'ϱ': r'\varrho', 'ϖ': r'\varpi', 'ℓ': r'\ell',
    }

    OPERATOR_MAP = {
        '∑': r'\sum', '∏': r'\prod', '∫': r'\int', '∬': r'\iint',
        '∮': r'\oint', '√': r'\sqrt', '∞': r'\infty', '≈': r'\approx',
        '≠': r'\neq', '≤': r'\leq', '≥': r'\geq', '±': r'\pm',
        '∓': r'\mp', '×': r'\times', '÷': r'\div', '∈': r'\in',
        '∉': r'\notin', '⊂': r'\subset', '⊃': r'\supset', '∪': r'\cup',
        '∩': r'\cap', '∧': r'\wedge', '∨': r'\vee', '¬': r'\neg',
        '→': r'\rightarrow', '←': r'\leftarrow', '↔': r'\leftrightarrow',
        '⇒': r'\Rightarrow', '⇐': r'\Leftarrow', '⇔': r'\Leftrightarrow',
        '∀': r'\forall', '∃': r'\exists', '∅': r'\emptyset',
        '∂': r'\partial', '∇': r'\nabla', '·': r'\cdot',
        '…': r'\ldots', '⋯': r'\cdots', '⋮': r'\vdots', '⋱': r'\ddots',
        '|': r'|',
        '‖': r'\|',
        '⌈': r'\lceil', '⌉': r'\rceil', '⌊': r'\lfloor', '⌋': r'\rfloor',
        '\u2061': '',  # function application (invisible)
    }

    def __init__(self):
        pass

    def convert(self, elem):
        """Convert an oMath or oMathPara element to LaTeX."""
        tag = self._local(elem.tag)
        if tag == 'oMathPara':
            # Display math
            parts = []
            for child in elem:
                if self._local(child.tag) == 'oMath':
                    parts.append(self._process(child))
            return '$$\n' + '\n'.join(parts) + '\n$$'
        elif tag == 'oMath':
            return self._process(elem)
        else:
            return self._process(elem)

    def _local(self, tag):
        """Strip namespace from tag."""
        if '}' in tag:
            return tag.split('}', 1)[1]
        return tag

    def _process(self, elem):
        """Recursively process an OMML element."""
        tag = self._local(elem.tag)
        method = getattr(self, f'_handle_{tag}', None)
        if method:
            return method(elem)
        # Default: process children
        return self._process_children(elem)

    def _process_children(self, elem):
        parts = []
        for child in elem:
            parts.append(self._process(child))
        return ''.join(parts)

    def _get_text(self, elem):
        """Get all text content from an element."""
        texts = []
        for t_elem in elem.iter(qn('m:t')):
            if t_elem.text:
                texts.append(t_elem.text)
        return ''.join(texts)

    def _translate_char(self, c):
        """Translate a character to its LaTeX equivalent.

        LaTeX backslash-commands (\\geq, \\neg, \\wedge, …) must be
        followed by a space so they don't merge with the next token.
        Single-symbol operators (+, −, |, …) need no space.
        """
        if c in self.GREEK_MAP:
            return self.GREEK_MAP[c] + ' '
        if c in self.OPERATOR_MAP:
            mapped = self.OPERATOR_MAP[c]
            # Add trailing space after \command-style operators
            if mapped.startswith('\\') and mapped[1:].isalpha():
                return mapped + ' '
            return mapped
        return c

    def _translate_text(self, text):
        """Translate a text string, mapping special chars."""
        result = []
        for c in text:
            result.append(self._translate_char(c))
        out = ''.join(result)
        # Escape percent signs for LaTeX
        out = out.replace('%', r'\%')
        return out

    # ── Element handlers ──────────────────────────────────────────────────

    def _handle_oMath(self, elem):
        return self._process_children(elem)

    def _handle_oMathPara(self, elem):
        parts = []
        for child in elem:
            if self._local(child.tag) == 'oMath':
                parts.append(self._process(child))
        return '\n'.join(parts)

    def _handle_r(self, elem):
        """Math run - contains text.

        If the run has ``<m:rPr><m:nor/>`` (normal/upright style) AND
        contains multi-character prose (not a single operator/variable),
        wrap in ``\\text{}``.
        """
        text = self._get_text(elem)
        if not text:
            return ''

        # Check for <m:nor/> (normal text) in run properties
        is_normal = False
        rPr = elem.find(qn('m:rPr'))
        if rPr is not None:
            nor = rPr.find(qn('m:nor'))
            if nor is not None:
                is_normal = True

        if is_normal and len(text) > 1 and any(c.isalpha() for c in text):
            # Check if the text is all-operator/single-symbol — don't wrap those
            # Only wrap actual prose words
            stripped = text.strip()
            if ' ' in stripped or len(stripped) > 3:
                # Multi-word or long prose text → wrap in \text{}
                return r'\text{' + text + '}'
            # Short text like "≥" or "=" — translate normally
            return self._translate_text(text)
        return self._translate_text(text)

    def _handle_t(self, elem):
        if elem.text:
            return self._translate_text(elem.text)
        return ''

    def _handle_f(self, elem):
        """Fraction."""
        num = ''
        den = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'num':
                num = self._process_children(child)
            elif lt == 'den':
                den = self._process_children(child)
        return r'\frac{' + num.strip() + '}{' + den.strip() + '}'

    def _handle_num(self, elem):
        return self._process_children(elem)

    def _handle_den(self, elem):
        return self._process_children(elem)

    def _handle_sSup(self, elem):
        """Superscript."""
        base = ''
        sup = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'e':
                base = self._process_children(child)
            elif lt == 'sup':
                sup = self._process_children(child)
        sup_s = sup.strip()
        if len(sup_s) == 1:
            return base.strip() + '^' + sup_s
        return base.strip() + '^{' + sup_s + '}'

    def _handle_sSub(self, elem):
        """Subscript."""
        base = ''
        sub = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'e':
                base = self._process_children(child)
            elif lt == 'sub':
                sub = self._process_children(child)
        sub_s = sub.strip()
        if len(sub_s) == 1:
            return base.strip() + '_' + sub_s
        return base.strip() + '_{' + sub_s + '}'

    def _handle_sSubSup(self, elem):
        """Sub-superscript."""
        base = ''
        sub = ''
        sup = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'e':
                base = self._process_children(child)
            elif lt == 'sub':
                sub = self._process_children(child)
            elif lt == 'sup':
                sup = self._process_children(child)
        result = base.strip()
        sub_s = sub.strip()
        sup_s = sup.strip()
        if sub_s:
            result += '_{' + sub_s + '}'
        if sup_s:
            result += '^{' + sup_s + '}'
        return result

    def _handle_e(self, elem):
        """Base element."""
        return self._process_children(elem)

    def _handle_sup(self, elem):
        return self._process_children(elem)

    def _handle_sub(self, elem):
        return self._process_children(elem)

    def _handle_d(self, elem):
        """Delimiter (parentheses, brackets, etc.)."""
        # Get delimiter properties
        beg_chr = '('
        end_chr = ')'
        for dPr in elem.iter(qn('m:dPr')):
            for bc in dPr.iter(qn('m:begChr')):
                val = bc.get(qn('m:val'))
                if val is not None:
                    beg_chr = val
            for ec in dPr.iter(qn('m:endChr')):
                val = ec.get(qn('m:val'))
                if val is not None:
                    end_chr = val

        # Translate delimiters
        delim_map = {
            '(': r'\left(', ')': r'\right)',
            '[': r'\left[', ']': r'\right]',
            '{': r'\left\{', '}': r'\right\}',
            '|': r'\left|', '‖': r'\left\|',
            '⌈': r'\left\lceil', '⌉': r'\right\rceil',
            '⌊': r'\left\lfloor', '⌋': r'\right\rfloor',
            '⟨': r'\left\langle', '⟩': r'\right\rangle',
        }
        left = delim_map.get(beg_chr, r'\left' + beg_chr)
        right = delim_map.get(end_chr, r'\right' + end_chr)
        if end_chr == '' or end_chr is None:
            right = r'\right.'
        if beg_chr == '' or beg_chr is None:
            left = r'\left.'

        content = self._process_children(elem)
        return left + content.strip() + right

    def _handle_nary(self, elem):
        """N-ary operator (sum, product, integral, etc.)."""
        op_char = '∫'
        sub_content = ''
        sup_content = ''
        base_content = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'naryPr':
                for chr_elem in child.iter(qn('m:chr')):
                    val = chr_elem.get(qn('m:val'))
                    if val:
                        op_char = val
            elif lt == 'sub':
                sub_content = self._process_children(child)
            elif lt == 'sup':
                sup_content = self._process_children(child)
            elif lt == 'e':
                base_content = self._process_children(child)

        op_latex = self._translate_char(op_char)
        result = op_latex
        if sub_content.strip():
            result += '_{' + sub_content.strip() + '}'
        if sup_content.strip():
            result += '^{' + sup_content.strip() + '}'
        result += ' ' + base_content.strip()
        return result

    def _handle_rad(self, elem):
        """Radical (square root, nth root)."""
        deg = ''
        base = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'deg':
                deg = self._process_children(child).strip()
            elif lt == 'e':
                base = self._process_children(child)
        if deg and deg != '2':
            return r'\sqrt[' + deg + ']{' + base.strip() + '}'
        return r'\sqrt{' + base.strip() + '}'

    def _handle_acc(self, elem):
        """Accent (hat, tilde, bar, dot, etc.)."""
        accent_char = '\u0302'  # default: hat
        base = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'accPr':
                for chr_elem in child.iter(qn('m:chr')):
                    val = chr_elem.get(qn('m:val'))
                    if val:
                        accent_char = val
            elif lt == 'e':
                base = self._process_children(child)
        latex_cmd = self.ACCENT_MAP.get(accent_char, r'\hat')
        return latex_cmd + '{' + base.strip() + '}'

    def _handle_bar(self, elem):
        """Overbar / underbar."""
        base = ''
        pos = 'top'
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'barPr':
                for p in child.iter(qn('m:pos')):
                    val = p.get(qn('m:val'))
                    if val:
                        pos = val
            elif lt == 'e':
                base = self._process_children(child)
        if pos == 'bot':
            return r'\underline{' + base.strip() + '}'
        return r'\overline{' + base.strip() + '}'

    def _handle_m(self, elem):
        """Matrix.  Detect 'cases' pattern (plcHide=on inside a { delimiter)."""
        # Check if placeholder is hidden (typical for cases environment)
        is_cases = False
        mPr = elem.find(qn('m:mPr'))
        if mPr is not None:
            plcHide = mPr.find(qn('m:plcHide'))
            if plcHide is not None and plcHide.get(qn('m:val'), '') == 'on':
                is_cases = True

        rows = []
        for mr in elem:
            if self._local(mr.tag) == 'mr':
                cells = []
                for e in mr:
                    if self._local(e.tag) == 'e':
                        cells.append(self._process_children(e).strip())
                rows.append(' & '.join(cells))

        if is_cases:
            return r'\begin{cases}' + ' \\\\ '.join(rows) + r'\end{cases}'
        return r'\begin{pmatrix}' + ' \\\\ '.join(rows) + r'\end{pmatrix}'

    def _handle_mr(self, elem):
        return self._process_children(elem)

    def _handle_func(self, elem):
        """Function application (sin, cos, log, etc.)."""
        fname = ''
        farg = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'fName':
                fname = self._process_children(child).strip()
            elif lt == 'e':
                farg = self._process_children(child)
        # Common function names
        known_funcs = ['sin', 'cos', 'tan', 'log', 'ln', 'exp', 'lim',
                       'max', 'min', 'sup', 'inf', 'det', 'dim', 'arg',
                       'Pr', 'gcd', 'lcm', 'mod']
        if fname.lower() in [f.lower() for f in known_funcs]:
            return '\\' + fname + ' ' + farg
        return r'\operatorname{' + fname + '}' + farg

    def _handle_fName(self, elem):
        return self._process_children(elem)

    def _handle_limLow(self, elem):
        """Lower limit."""
        base = ''
        lim = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'e':
                base = self._process_children(child)
            elif lt == 'lim':
                lim = self._process_children(child)
        return base.strip() + '_{' + lim.strip() + '}'

    def _handle_limUpp(self, elem):
        """Upper limit."""
        base = ''
        lim = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'e':
                base = self._process_children(child)
            elif lt == 'lim':
                lim = self._process_children(child)
        return base.strip() + '^{' + lim.strip() + '}'

    def _handle_lim(self, elem):
        return self._process_children(elem)

    def _handle_eqArr(self, elem):
        """Equation array (aligned equations)."""
        rows = []
        for child in elem:
            if self._local(child.tag) == 'e':
                rows.append(self._process_children(child).strip())
        return r'\begin{aligned}' + ' \\\\ '.join(rows) + r'\end{aligned}'

    def _handle_box(self, elem):
        return self._process_children(elem)

    def _handle_borderBox(self, elem):
        return r'\boxed{' + self._process_children(elem).strip() + '}'

    def _handle_sPre(self, elem):
        """Pre-script (left sub/superscript)."""
        sub = ''
        sup = ''
        base = ''
        for child in elem:
            lt = self._local(child.tag)
            if lt == 'sub':
                sub = self._process_children(child)
            elif lt == 'sup':
                sup = self._process_children(child)
            elif lt == 'e':
                base = self._process_children(child)
        result = ''
        if sub.strip():
            result += '_{' + sub.strip() + '}'
        if sup.strip():
            result += '^{' + sup.strip() + '}'
        return result + base

    # Property elements - skip
    def _handle_rPr(self, elem): return ''
    def _handle_ctrlPr(self, elem): return ''
    def _handle_fPr(self, elem): return ''
    def _handle_dPr(self, elem): return ''
    def _handle_naryPr(self, elem): return ''
    def _handle_radPr(self, elem): return ''
    def _handle_accPr(self, elem): return ''
    def _handle_barPr(self, elem): return ''
    def _handle_mPr(self, elem): return ''
    def _handle_funcPr(self, elem): return ''
    def _handle_limLowPr(self, elem): return ''
    def _handle_limUppPr(self, elem): return ''
    def _handle_sSubPr(self, elem): return ''
    def _handle_sSupPr(self, elem): return ''
    def _handle_sSubSupPr(self, elem): return ''
    def _handle_eqArrPr(self, elem): return ''
    def _handle_boxPr(self, elem): return ''
    def _handle_borderBoxPr(self, elem): return ''
    def _handle_sPrePr(self, elem): return ''
    def _handle_oMathParaPr(self, elem): return ''
    def _handle_mcJc(self, elem): return ''
    def _handle_mc(self, elem): return ''
    def _handle_mcs(self, elem): return ''


# ═══════════════════════════════════════════════════════════════════════════
#  HYPERLINK RESOLVER
# ═══════════════════════════════════════════════════════════════════════════

def resolve_hyperlinks(docx_path):
    """Extract rId → URL mapping from document.xml.rels."""
    rels = {}
    with zipfile.ZipFile(docx_path, 'r') as z:
        rels_path = 'word/_rels/document.xml.rels'
        if rels_path in z.namelist():
            tree = ET.parse(z.open(rels_path))
            root = tree.getroot()
            for rel in root:
                tag = rel.tag
                if '}' in tag:
                    tag = tag.split('}', 1)[1]
                if tag == 'Relationship':
                    rid = rel.get('Id', '')
                    target = rel.get('Target', '')
                    rel_type = rel.get('Type', '')
                    if 'hyperlink' in rel_type:
                        rels[rid] = target
    return rels


# ═══════════════════════════════════════════════════════════════════════════
#  CODE LANGUAGE GUESSER
# ═══════════════════════════════════════════════════════════════════════════

def guess_language(code_text):
    """Guess programming language from code content."""
    text = code_text.strip()

    # Python indicators
    if re.search(r'\bimport\s+\w+|from\s+\w+\s+import|def\s+\w+\(|class\s+\w+[:(]|print\(', text):
        if not re.search(r'\bfunction\b|const\s|let\s|var\s|=>|require\(', text):
            return 'python'

    # TypeScript/JavaScript
    if re.search(r'\bimport\s*\{.*\}\s*from\s|export\s+(default\s+)?|const\s+\w+\s*[=:]|interface\s+\w+|type\s+\w+\s*=', text):
        if re.search(r':\s*(string|number|boolean|any|void)\b|interface\s|<\w+>', text):
            return 'typescript'
        return 'javascript'

    # JavaScript
    if re.search(r'\bfunction\b|const\s|let\s|var\s|=>\s*\{|require\(|module\.exports', text):
        return 'javascript'

    # Java/Kotlin
    if re.search(r'\bpublic\s+(class|static|void)|private\s+\w|System\.out', text):
        return 'java'

    # JSON
    if text.startswith('{') and text.endswith('}') and '"' in text:
        try:
            import json
            json.loads(text)
            return 'json'
        except Exception:
            pass

    # YAML
    if re.search(r'^\w+:\s*\n\s+\w+:', text, re.MULTILINE):
        return 'yaml'

    # XML/HTML
    if re.search(r'<\?xml|<html|<div|<span|xmlns:', text):
        return 'xml'

    # Shell
    if re.search(r'^\s*(#!/bin/|curl\s|wget\s|apt\s|pip\s|npm\s|git\s)', text, re.MULTILINE):
        return 'bash'

    # SQL
    if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE)\b', text, re.IGNORECASE):
        return 'sql'

    # Mermaid
    if re.match(r'^(sequenceDiagram|flowchart|graph\s|classDiagram|stateDiagram|erDiagram|gantt|pie|gitgraph)', text):
        return 'mermaid'

    # C/C++
    if re.search(r'#include\s*<|int\s+main\(|printf\(|std::', text):
        return 'cpp'

    # Rust
    if re.search(r'\bfn\s+\w+|let\s+mut\s|impl\s+\w+|pub\s+fn', text):
        return 'rust'

    # Go
    if re.search(r'\bfunc\s+\w+|package\s+\w+|fmt\.Print', text):
        return 'go'

    return ''


# ═══════════════════════════════════════════════════════════════════════════
#  MERMAID DETECTION
# ═══════════════════════════════════════════════════════════════════════════

MERMAID_STARTERS = [
    'sequenceDiagram', 'flowchart', 'graph ', 'graph\n',
    'classDiagram', 'stateDiagram', 'erDiagram',
    'gantt', 'pie', 'gitgraph', 'journey',
    'mindmap', 'timeline', 'sankey', 'quadrantChart',
    'xychart', 'block-beta', 'packet-beta',
]

def is_mermaid_start(text):
    """Check if text starts with a Mermaid diagram type."""
    stripped = text.strip()
    for starter in MERMAID_STARTERS:
        if stripped.startswith(starter):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  ESCAPE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def escape_md(text):
    """Escape text for Markdown rendering. Handles <Name> patterns."""
    # Don't escape empty strings
    if not text:
        return text
    # Escape angle brackets that would be interpreted as HTML
    text = re.sub(r'<(?!/?(a|b|i|em|strong|code|pre|br|hr|img|table|tr|td|th|thead|tbody|ul|ol|li|p|div|span|h[1-6])\b)', r'\<', text)
    # Escape remaining > that might break rendering
    # But be careful not to double-escape
    return text


def escape_table_cell(text):
    """Escape text for use inside a Markdown table cell."""
    text = escape_md(text)
    text = text.replace('|', r'\|')
    text = text.replace('\n', '<br>')
    return text


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN CONVERTER CLASS
# ═══════════════════════════════════════════════════════════════════════════

class DocxToMarkdown:
    def __init__(self, docx_path, output_path=None):
        self.docx_path = docx_path
        self.output_path = output_path or Path(docx_path).with_suffix('.md')
        self.doc = Document(docx_path)
        self.hyperlinks = resolve_hyperlinks(docx_path)
        self.math_converter = MathMLToLatex()
        self.footnote_links = {}  # citation_text -> url
        self.footnote_counter = 0
        self.footnotes_collected = []  # (number, url)
        self.output_lines = []
        # Bibliography detection
        self.bib_start_idx = None   # element index where bibliography starts
        self.bib_footnotes = {}     # {int(citation_num) -> url} from bibliography

    # ── Bibliography detection ────────────────────────────────────────────

    def _detect_bibliography(self, elements):
        """Detect the ChatGPT DeepResearch bibliography section at the end.

        DeepResearch exports end with a bibliography that groups citation
        numbers by URL.  Two observed patterns:

        Pattern A (doc2):
          P: "[1] [10] [24] [80] https://example.com/..."
          P: "https://example.com/..."

        Pattern B (doc1):
          P: "[12] [22] [37] [62] [66] openreview.net"   (title/domain)
          P: "https://openreview.net/..."                 (URL)

        Both patterns consist of consecutive BodyText paragraphs at the
        very end of the document.  We scan backwards from the end to find
        where the bibliography starts, then parse entries forward.
        """
        # Step 1: Scan backwards to find the bibliography boundary.
        # Skip trailing non-paragraph elements (bookmarkEnd, sectPr, etc.)
        # that Word places at the very end, then scan bibliography paragraphs.
        bib_entries_raw = []  # [(element_index, raw_text, hyperlinks_in_para)]
        found_first_para = False

        for i in range(len(elements) - 1, -1, -1):
            elem = elements[i]
            tag = self._local(elem.tag)
            if tag != 'p':
                if not found_first_para:
                    continue   # skip trailing non-paragraph elements
                else:
                    break      # hit non-paragraph inside content — stop
            found_first_para = True

            raw = self._get_raw_text(elem).strip()

            # Is this a bibliography-like paragraph?
            is_bib = False
            if not raw:
                # Empty paragraph between bib entries — still part of bib
                is_bib = True
            elif re.match(r'^\[?\d+\]?(\s+\[?\d+\]?)*\s+', raw):
                # Starts with [N] or N] groups: citation entry line
                is_bib = True
            elif re.match(r'^https?://', raw):
                # Pure URL line (second line of a 2-line entry)
                is_bib = True
            elif re.match(r'^[a-zA-Z]', raw) and len(raw) < 200:
                # Potential title line (e.g. "openreview.net", "GitHub - ...")
                # Only count as bib if the next line (below) was already bib
                if bib_entries_raw:
                    is_bib = True

            if is_bib:
                bib_entries_raw.insert(0, (i, raw, elem))
            else:
                break

        if not bib_entries_raw:
            return

        self.bib_start_idx = bib_entries_raw[0][0]

        # Step 2: Parse entries forward to build {citation_num -> URL}
        # Process pairs/groups of lines
        pending_citations = []
        pending_url = None

        for _, raw, elem in bib_entries_raw:
            if not raw:
                continue

            # Extract citation numbers like [1] [10] [24]
            citation_nums = [int(m) for m in re.findall(r'\[(\d+)\]', raw)]

            # Extract URL from text or from hyperlinks in this paragraph
            url_in_text = re.search(r'(https?://\S+)', raw)
            url_from_hyperlink = None
            for hl in elem.iter(qn('w:hyperlink')):
                rid = hl.get(qn('r:id'), '')
                if rid and rid in self.hyperlinks:
                    url_from_hyperlink = self.hyperlinks[rid]
                    break

            url = None
            if url_in_text:
                url = url_in_text.group(1)
            elif url_from_hyperlink:
                url = url_from_hyperlink

            if citation_nums:
                # This is a citation-numbers line, possibly with URL
                if url:
                    # Complete entry: citations + URL on same line
                    for n in citation_nums:
                        self.bib_footnotes[n] = url
                    pending_citations = []
                else:
                    # Citations without URL: URL will be on next line
                    pending_citations = citation_nums
            elif url and pending_citations:
                # URL-only line following citations
                for n in pending_citations:
                    self.bib_footnotes[n] = url
                pending_citations = []
            elif url and not citation_nums:
                # Standalone URL line (duplicate of previous entry) — skip
                pass

    def _is_bibliography_element(self, elements, idx):
        """Check if the element at idx is inside the bibliography section."""
        if self.bib_start_idx is not None and idx >= self.bib_start_idx:
            return True
        return False

    def convert(self):
        """Main conversion entry point."""
        body = self.doc.element.body
        elements = list(body)

        # Phase 1: Detect bibliography section and extract footnote data
        self._detect_bibliography(elements)

        # Phase 2: Convert document content (excluding bibliography)
        idx = 0
        while idx < len(elements):
            # Skip bibliography section entirely
            if self._is_bibliography_element(elements, idx):
                idx += 1
                continue

            elem = elements[idx]
            tag = self._local(elem.tag)

            if tag == 'p':
                idx = self._handle_paragraph_group(elements, idx)
            elif tag == 'tbl':
                self._handle_table(elem)
                idx += 1
            elif tag == 'sdt':
                # Structured document tag - process children
                for child in elem.iter(qn('w:p')):
                    pass
                idx += 1
            else:
                idx += 1

        # No footnote definitions needed: citation links are now rendered
        # as plain inline links [N](url) which are clickable in Obsidian.

        return '\n'.join(self.output_lines)

    def _local(self, tag):
        if tag and '}' in tag:
            return tag.split('}', 1)[1]
        return tag or ''

    # ── Paragraph grouping (code blocks, mermaid, lists) ──────────────────

    def _handle_paragraph_group(self, elements, start_idx):
        """Handle a paragraph, possibly grouping consecutive code/mermaid/list paragraphs."""
        elem = elements[start_idx]

        # Check if this is a code-style paragraph
        if self._is_code_paragraph(elem):
            return self._handle_code_block(elements, start_idx)

        # Check if this looks like the start of a Mermaid diagram
        para_text = self._get_raw_text(elem)
        if is_mermaid_start(para_text):
            return self._handle_mermaid_block(elements, start_idx)

        # Check if this is a list item
        if self._is_list_item(elem):
            return self._handle_list_group(elements, start_idx)

        # Regular paragraph
        self._handle_single_paragraph(elem)
        return start_idx + 1

    def _is_code_paragraph(self, elem):
        """Check if paragraph uses SourceCode style."""
        pPr = elem.find(qn('w:pPr'))
        if pPr is not None:
            pStyle = pPr.find(qn('w:pStyle'))
            if pStyle is not None:
                val = pStyle.get(qn('w:val'), '')
                if 'SourceCode' in val or 'source-code' in val.lower() or 'sourcecode' in val.lower():
                    return True
        # Also check run styles
        for run in elem.iter(qn('w:r')):
            rPr = run.find(qn('w:rPr'))
            if rPr is not None:
                rStyle = rPr.find(qn('w:rStyle'))
                if rStyle is not None:
                    val = rStyle.get(qn('w:val'), '')
                    if 'SourceCode' in val or 'source-code' in val.lower() or 'sourcecode' in val.lower():
                        return True
                # Check for monospace font
                rFonts = rPr.find(qn('w:rFonts'))
                if rFonts is not None:
                    for attr in ['w:ascii', 'w:hAnsi', 'w:cs']:
                        font = rFonts.get(qn(attr), '')
                        if font.lower() in ['consolas', 'courier new', 'courier', 'monospace',
                                              'source code pro', 'fira code', 'jetbrains mono',
                                              'cascadia code', 'roboto mono', 'menlo', 'monaco']:
                            return True
        return False

    def _is_inline_code_run(self, run_elem):
        """Check if a single run uses code styling."""
        rPr = run_elem.find(qn('w:rPr'))
        if rPr is not None:
            rStyle = rPr.find(qn('w:rStyle'))
            if rStyle is not None:
                val = rStyle.get(qn('w:val'), '')
                if 'SourceCode' in val or 'source-code' in val.lower() or 'sourcecode' in val.lower():
                    return True
            rFonts = rPr.find(qn('w:rFonts'))
            if rFonts is not None:
                for attr in ['w:ascii', 'w:hAnsi', 'w:cs']:
                    font = rFonts.get(qn(attr), '')
                    if font.lower() in ['consolas', 'courier new', 'courier', 'monospace',
                                          'source code pro', 'fira code', 'jetbrains mono',
                                          'cascadia code', 'roboto mono', 'menlo', 'monaco']:
                        return True
        return False

    def _is_list_item(self, elem):
        """Check if paragraph is a list item."""
        pPr = elem.find(qn('w:pPr'))
        if pPr is not None:
            numPr = pPr.find(qn('w:numPr'))
            if numPr is not None:
                return True
        return False

    def _get_list_info(self, elem):
        """Get list level and numbering ID."""
        pPr = elem.find(qn('w:pPr'))
        if pPr is not None:
            numPr = pPr.find(qn('w:numPr'))
            if numPr is not None:
                ilvl_elem = numPr.find(qn('w:ilvl'))
                numId_elem = numPr.find(qn('w:numId'))
                ilvl = int(ilvl_elem.get(qn('w:val'), '0')) if ilvl_elem is not None else 0
                numId = numId_elem.get(qn('w:val'), '0') if numId_elem is not None else '0'
                return ilvl, numId
        return 0, '0'

    def _get_raw_text(self, elem):
        """Get plain text from paragraph element."""
        texts = []
        for t in elem.iter(qn('w:t')):
            if t.text:
                texts.append(t.text)
        for t in elem.iter(qn('m:t')):
            if t.text:
                texts.append(t.text)
        return ''.join(texts)

    # ── Code block handling ───────────────────────────────────────────────

    def _handle_code_block(self, elements, start_idx):
        """Collect consecutive code paragraphs into a fenced code block.

        In ChatGPT DeepResearch exports, each code "block" is typically a
        single paragraph with internal <w:br/> for line breaks.  Multiple
        consecutive SourceCode paragraphs are joined with an extra newline.
        """
        code_lines = []
        idx = start_idx

        while idx < len(elements):
            elem = elements[idx]
            tag = self._local(elem.tag)
            if tag != 'p':
                break
            if not self._is_code_paragraph(elem):
                break
            # Get the raw text preserving spaces and internal line breaks
            line = self._get_code_line(elem)
            code_lines.append(line)
            idx += 1

        # Join paragraphs – each already contains internal newlines from <w:br/>
        code_text = '\n'.join(code_lines)

        # Strip trailing whitespace per line but preserve indentation
        code_text = '\n'.join(l.rstrip() for l in code_text.split('\n'))
        # Remove trailing empty lines
        code_text = code_text.rstrip('\n')

        # Check if it's mermaid
        if is_mermaid_start(code_text):
            # Escape curly braces inside node labels.
            # Mermaid uses { } for diamond (decision) nodes, so any
            # literal braces in rectangle [ ] labels cause parse errors.
            # Fix: quote labels that contain braces, e.g. [text] → ["text"]
            code_text = self._fix_mermaid_special_chars(code_text)
            self.output_lines.append('')
            self.output_lines.append('```mermaid')
            self.output_lines.append(code_text)
            self.output_lines.append('```')
            self.output_lines.append('')
        else:
            lang = guess_language(code_text)
            self.output_lines.append('')
            self.output_lines.append(f'```{lang}')
            self.output_lines.append(code_text)
            self.output_lines.append('```')
            self.output_lines.append('')

        return idx

    @staticmethod
    def _fix_mermaid_special_chars(code_text):
        """Quote Mermaid node labels and edge labels that contain special chars.

        Mermaid reserves several bracket characters for node shapes:
        - ``{text}`` → diamond node
        - ``(text)`` → rounded node
        - ``[text]`` → rectangle node

        Literal braces or parentheses inside labels cause parse errors.
        Fix: quote the label content, e.g. ``[text]`` → ``["text"]``.

        Also handles edge labels like ``-- text -->`` which need quoting
        when they contain parentheses: ``-- "text" -->``.
        """
        def _quote_if_special(m):
            bracket = m.group(1)   # [ or ( etc.
            content = m.group(2)
            close = m.group(3)     # ] or ) etc.
            if '{' in content or '}' in content or '(' in content or ')' in content:
                if content.startswith('"') and content.endswith('"'):
                    return m.group(0)
                return f'{bracket}"{content}"{close}'
            return m.group(0)

        # Fix node labels in square brackets: [label]
        code_text = re.sub(
            r'(\[)([^\]]+?)(\])',
            _quote_if_special,
            code_text
        )

        # Fix edge labels: -- label --> or -- label ---
        # These appear between -- and --> (or ---) on arrow lines.
        def _quote_edge_label(m):
            prefix = m.group(1)   # "-- " or "== "
            label = m.group(2)
            suffix = m.group(3)   # " -->" or " ---" etc.
            if '(' in label or ')' in label or '{' in label or '}' in label:
                if label.startswith('"') and label.endswith('"'):
                    return m.group(0)
                return f'{prefix}"{label}"{suffix}'
            return m.group(0)

        code_text = re.sub(
            r'(--\s+)(.+?)(\s+-->|--\s)',
            _quote_edge_label,
            code_text
        )

        return code_text

    def _get_code_line(self, elem):
        """Extract code text from a paragraph, preserving whitespace and line breaks.

        ChatGPT DeepResearch exports code blocks as single paragraphs with
        <w:br/> elements separating lines within runs.
        """
        parts = []
        for child in elem:
            tag = self._local(child.tag)
            if tag == 'r':
                # Process children of the run in order to preserve <br/> placement
                for sub in child:
                    stag = self._local(sub.tag)
                    if stag == 't':
                        if sub.text:
                            parts.append(sub.text)
                    elif stag == 'br':
                        parts.append('\n')
                    elif stag == 'tab':
                        parts.append('\t')
                    elif stag == 'rPr':
                        continue
            elif tag == 'pPr':
                continue
            elif tag == 'hyperlink':
                for r in child.iter(qn('w:r')):
                    for sub in r:
                        stag = self._local(sub.tag)
                        if stag == 't' and sub.text:
                            parts.append(sub.text)
                        elif stag == 'br':
                            parts.append('\n')
                        elif stag == 'tab':
                            parts.append('\t')
        return ''.join(parts)

    # ── Mermaid block handling ────────────────────────────────────────────

    def _handle_mermaid_block(self, elements, start_idx):
        """Collect consecutive paragraphs that form a Mermaid diagram."""
        mermaid_lines = []
        idx = start_idx

        # Collect lines that look like they belong to the diagram
        while idx < len(elements):
            elem = elements[idx]
            tag = self._local(elem.tag)
            if tag != 'p':
                break

            text = self._get_raw_text(elem).rstrip()

            # First line always included
            if idx == start_idx:
                mermaid_lines.append(text)
                idx += 1
                continue

            # Subsequent lines: check if they look like Mermaid content
            if self._looks_like_mermaid_content(text):
                mermaid_lines.append(text)
                idx += 1
            else:
                break

        # Reconstruct with proper indentation from code lines
        diagram_lines = []
        for i, elem_idx in enumerate(range(start_idx, idx)):
            line = self._get_code_line(elements[elem_idx]) if self._is_code_paragraph(elements[elem_idx]) else self._get_raw_text(elements[elem_idx])
            diagram_lines.append(line)

        diagram_text = '\n'.join(diagram_lines)
        diagram_text = self._fix_mermaid_special_chars(diagram_text)

        self.output_lines.append('')
        self.output_lines.append('```mermaid')
        self.output_lines.append(diagram_text)
        self.output_lines.append('```')
        self.output_lines.append('')

        return idx

    def _looks_like_mermaid_content(self, text):
        """Heuristic: does this text look like part of a Mermaid diagram?"""
        stripped = text.strip()
        if not stripped:
            return True  # blank lines can be part of diagram
        # Mermaid keywords and patterns
        mermaid_patterns = [
            r'^\s*(participant|actor|Note\s|loop\s|alt\s|else\s|end|opt\s|par\s|rect\s)',
            r'^\s*\w+\s*(->>|-->>|->|-->|--x|--\)|-\)|-x)\s*\w+',  # sequence arrows
            r'^\s*\w+\s*(-->|---|\.-\.>|==>)\s*',  # flowchart arrows
            r'^\s*subgraph\s',
            r'^\s*(classDef|class)\s',
            r'^\s*\w+\[',   # node definitions
            r'^\s*\w+\(',   # node definitions
            r'^\s*\w+\{',   # node definitions
            r'^\s*%%',       # mermaid comments
            r'^\s*(LR|RL|TB|TD|BT)\s*$',  # direction
            r'^\s*partic',   # truncated participant
            r'^\s*activate\s',
            r'^\s*deactivate\s',
        ]
        for pat in mermaid_patterns:
            if re.search(pat, stripped):
                return True

        # If we're in a code-styled paragraph, it's likely continuation
        return False

    # ── List handling ─────────────────────────────────────────────────────

    def _handle_list_group(self, elements, start_idx):
        """Handle consecutive list items."""
        idx = start_idx
        # Track numbering per (numId, level)
        counters = {}

        while idx < len(elements):
            elem = elements[idx]
            tag = self._local(elem.tag)
            if tag != 'p':
                break
            if not self._is_list_item(elem):
                break

            ilvl, numId = self._get_list_info(elem)
            indent = '  ' * ilvl

            # Determine bullet vs number
            # In ChatGPT DeepResearch exports, the numbering format info is in abstractNum
            # We'll use a heuristic: check the paragraph text for leading numbers
            para_md = self._render_paragraph_inline(elem)
            text_stripped = para_md.strip()

            # Check if it starts with a number pattern like "1." "2." etc.
            num_match = re.match(r'^(\d+)\.\s', text_stripped)
            alpha_match = re.match(r'^([a-z])\)\s', text_stripped)

            key = (numId, ilvl)
            if num_match:
                # Already has number prefix from Word
                self.output_lines.append(f'{indent}{text_stripped}')
            elif alpha_match:
                self.output_lines.append(f'{indent}{text_stripped}')
            else:
                # Use bullet
                self.output_lines.append(f'{indent}- {text_stripped}')

            idx += 1

        self.output_lines.append('')
        return idx

    # ── Single paragraph handling ─────────────────────────────────────────

    def _handle_single_paragraph(self, elem):
        """Convert a single paragraph to Markdown."""
        # Check for heading
        heading_level = self._get_heading_level(elem)

        # Check for math paragraph (oMathPara)
        math_paras = list(elem.iter(qn('m:oMathPara')))
        if math_paras:
            for mp in math_paras:
                latex = self.math_converter.convert(mp)
                self.output_lines.append('')
                self.output_lines.append(f'$${latex.strip().lstrip("$").rstrip("$").strip()}$$')
                self.output_lines.append('')
            return

        # Render inline content
        md_text = self._render_paragraph_inline(elem)

        if not md_text.strip():
            # Empty paragraph - add blank line
            self.output_lines.append('')
            return

        if heading_level:
            prefix = '#' * heading_level + ' '
            self.output_lines.append('')
            self.output_lines.append(prefix + md_text.strip())
            self.output_lines.append('')
        else:
            self.output_lines.append('')
            self.output_lines.append(md_text)

    def _get_heading_level(self, elem):
        """Determine heading level from paragraph style."""
        pPr = elem.find(qn('w:pPr'))
        if pPr is not None:
            pStyle = pPr.find(qn('w:pStyle'))
            if pStyle is not None:
                val = pStyle.get(qn('w:val'), '')
                # Match Heading1, Heading2, etc. or "Heading 1", "heading1"
                m = re.match(r'[Hh]eading\s*(\d+)', val)
                if m:
                    return int(m.group(1))
        return 0

    # ── Inline rendering ──────────────────────────────────────────────────

    def _render_paragraph_inline(self, elem):
        """Render paragraph content as inline Markdown (handles runs, hyperlinks, math)."""
        parts = []
        self._render_children_inline(elem, parts)
        return ''.join(parts)

    def _render_children_inline(self, parent, parts):
        """Recursively render children of an element."""
        for child in parent:
            tag = self._local(child.tag)

            if tag == 'pPr':
                continue  # skip paragraph properties
            elif tag == 'r':
                self._render_run(child, parts)
            elif tag == 'hyperlink':
                self._render_hyperlink(child, parts)
            elif tag == 'oMath':
                latex = self.math_converter.convert(child)
                latex = latex.strip()
                # Inline math
                parts.append(f'${latex}$')
            elif tag == 'oMathPara':
                latex = self.math_converter.convert(child)
                parts.append(f'\n$${latex.strip().lstrip("$").rstrip("$").strip()}$$\n')
            elif tag == 'ins' or tag == 'del':
                # Track changes - render the content
                self._render_children_inline(child, parts)
            elif tag == 'bookmarkStart' or tag == 'bookmarkEnd':
                continue
            elif tag == 'proofErr':
                continue
            elif tag == 'sdt':
                # Structured document tag
                for sdtContent in child.iter(qn('w:sdtContent')):
                    self._render_children_inline(sdtContent, parts)
            else:
                # Try processing children
                self._render_children_inline(child, parts)

    def _render_run(self, run_elem, parts):
        """Render a single run with formatting."""
        rPr = run_elem.find(qn('w:rPr'))
        is_bold = False
        is_italic = False
        is_code = False

        if rPr is not None:
            # Check bold
            b = rPr.find(qn('w:b'))
            if b is not None:
                val = b.get(qn('w:val'))
                if val is None or val.lower() in ('true', '1', 'on'):
                    is_bold = True

            bCs = rPr.find(qn('w:bCs'))
            if bCs is not None and not is_bold:
                val = bCs.get(qn('w:val'))
                if val is None or val.lower() in ('true', '1', 'on'):
                    is_bold = True

            # Check italic
            i = rPr.find(qn('w:i'))
            if i is not None:
                val = i.get(qn('w:val'))
                if val is None or val.lower() in ('true', '1', 'on'):
                    is_italic = True

            iCs = rPr.find(qn('w:iCs'))
            if iCs is not None and not is_italic:
                val = iCs.get(qn('w:val'))
                if val is None or val.lower() in ('true', '1', 'on'):
                    is_italic = True

            # Check code style
            is_code = self._is_inline_code_run(run_elem)

        # Collect text
        text_parts = []
        for child in run_elem:
            ctag = self._local(child.tag)
            if ctag == 't':
                if child.text:
                    text_parts.append(child.text)
            elif ctag == 'tab':
                text_parts.append('\t')
            elif ctag == 'br':
                text_parts.append('\n')
            elif ctag == 'cr':
                text_parts.append('\n')
            elif ctag == 'sym':
                # Symbol
                char_code = child.get(qn('w:char'), '')
                if char_code:
                    try:
                        text_parts.append(chr(int(char_code, 16)))
                    except (ValueError, OverflowError):
                        text_parts.append('?')
            elif ctag == 'rPr':
                continue

        text = ''.join(text_parts)
        if not text:
            return

        if is_code:
            # Inline code - don't escape
            parts.append(f'`{text}`')
        else:
            # Escape for markdown
            text = escape_md(text)
            if is_bold and is_italic:
                parts.append(f'***{text}***')
            elif is_bold:
                parts.append(f'**{text}**')
            elif is_italic:
                parts.append(f'*{text}*')
            else:
                parts.append(text)

    def _render_hyperlink(self, hyperlink_elem, parts):
        """Render a hyperlink.

        Citation-style links ([1], [2], etc.) are rendered as plain
        inline links: ``[N](url)``.  In Obsidian this renders "N" as a
        small clickable number that opens the URL directly.

        Formats we deliberately avoid (Obsidian compatibility issues):
        - ``[^N]`` footnotes — only work in Reading mode, not Live Preview.
        - ``<sup>[N](url)</sup>`` — HTML not rendered in Obsidian.
        - ``[[N]](url)`` — creates broken wikilinks.
        """
        # Get the URL from relationship
        rid = hyperlink_elem.get(qn('r:id'), '')
        url = self.hyperlinks.get(rid, '')
        anchor = hyperlink_elem.get(qn('w:anchor'), '')

        # Get the display text
        display_parts = []
        for run in hyperlink_elem.iter(qn('w:r')):
            for t in run.iter(qn('w:t')):
                if t.text:
                    display_parts.append(t.text)
        display_text = ''.join(display_parts).strip()

        if not url and anchor:
            parts.append(display_text)
            return

        if not url:
            parts.append(display_text)
            return

        # Check if this is a citation-style link like [1], [2], etc.
        citation_match = re.match(r'^\[?(\d+)\]?$', display_text)
        if citation_match:
            fn_num = int(citation_match.group(1))
            # Prefer bibliography URL (canonical), fall back to hyperlink URL
            resolved_url = self.bib_footnotes.get(fn_num, url)
            parts.append(f'[{fn_num}]({resolved_url})')
        else:
            # Regular hyperlink
            escaped_display = escape_md(display_text)
            parts.append(f'[{escaped_display}]({url})')

    # ── Table handling ────────────────────────────────────────────────────

    def _handle_table(self, tbl_elem):
        """Convert a Word table to Markdown table."""
        rows = []
        for tr in tbl_elem.findall(qn('w:tr')):
            cells = []
            for tc in tr.findall(qn('w:tc')):
                cell_parts = []
                for p in tc.findall(qn('w:p')):
                    p_text = self._render_paragraph_inline(p)
                    cell_parts.append(p_text.strip())
                cell_text = ' '.join(cell_parts)
                cells.append(escape_table_cell(cell_text))
            rows.append(cells)

        if not rows:
            return

        # Normalize column count
        max_cols = max(len(row) for row in rows)
        for row in rows:
            while len(row) < max_cols:
                row.append('')

        # Output table
        self.output_lines.append('')

        # Header row
        header = rows[0]
        self.output_lines.append('| ' + ' | '.join(header) + ' |')

        # Separator
        self.output_lines.append('| ' + ' | '.join(['---'] * max_cols) + ' |')

        # Data rows
        for row in rows[1:]:
            self.output_lines.append('| ' + ' | '.join(row) + ' |')

        self.output_lines.append('')

    def save(self):
        """Run conversion and save to file."""
        md_content = self.convert()

        # ── Post-processing cleanup ──────────────────────────────────────

        # Clean up excessive blank lines
        md_content = re.sub(r'\n{4,}', '\n\n\n', md_content)
        # Remove leading blank lines
        md_content = md_content.lstrip('\n')

        # Fix bold formatting artifacts around inline math.
        # In ChatGPT DeepResearch exports, bold runs are split around math elements,
        # producing patterns like: **text** $N$ **more text**
        # which should be: **text $N$ more text**
        # We iteratively merge adjacent bold spans separated by inline math or spaces.
        for _ in range(5):  # iterate to handle nested/repeated patterns
            prev = md_content
            # Remove empty bold: **** or ** **
            md_content = re.sub(r'\*{4,}', '', md_content)
            md_content = re.sub(r'\*\*\s*\*\*', ' ', md_content)
            # Merge: **A** $X$ **B** → **A $X$ B**
            md_content = re.sub(r'\*\*\s*(\$[^$]+\$)\s*\*\*', r' \1 ', md_content)
            # Merge: **A** **B** → **A B**
            md_content = re.sub(r'\*\*\s+\*\*', ' ', md_content)
            if md_content == prev:
                break

        # Clean up any remaining bold artifacts: lonely ** at start/end of a pattern
        # e.g. "** text" without closing
        md_content = re.sub(r'\*\*\s*\*\*', ' ', md_content)

        # Ensure code block language identifiers don't have trailing spaces
        md_content = re.sub(r'```(\w+)\s+\n', r'```\1\n', md_content)

        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        return self.output_path


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: python docx2md.py <input.docx> [output.md]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.isfile(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not input_path.lower().endswith('.docx'):
        print(f"Warning: File does not have .docx extension: {input_path}", file=sys.stderr)

    try:
        converter = DocxToMarkdown(input_path, output_path)
        result = converter.save()
        print(f"Converted: {result}")
    except zipfile.BadZipFile:
        print(f"Error: Not a valid .docx file (bad ZIP): {input_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error converting {input_path}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
