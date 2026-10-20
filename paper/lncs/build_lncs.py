"""Build the Springer LNCS Word version of the manuscript.

Source: ../springer/manuscript_sn.tex (itself generated from ../manuscript.tex by build_sn.py).
Styles: Springer's LNCS Word template (splnproc2510.docm), reduced to a macro-free reference
document (lncs-reference.docx, made by `python3 -I build_lncs.py reference <unzipped .docm dir>`).

    python3 -I paper/lncs/build_lncs.py            # writes paper/lncs/manuscript_lncs.docx

Pipeline: LaTeX -> LaTeX that pandoc reads well -> pandoc (citeproc, LNCS CSL, reference doc,
lncs_filter.lua) -> post-processing that maps pandoc's paragraph styles onto the LNCS styles
(papertitle, author, abstract, keywords, heading1/2, p1a, figurecaption, tablecaption, image,
referenceitem, programcode). The TikZ architecture figure is rendered to PNG with tectonic.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = HERE.parent / "springer" / "manuscript_sn.tex"
BIB = HERE.parent / "references.bib"
REF = HERE / "lncs-reference.docx"
CSL = HERE / "lncs.csl"
FILTER = HERE / "lncs_filter.lua"
OUT = HERE / "manuscript_lncs.docx"
FIG = HERE / "figures"
SHORT_TITLE = "Execution Semantics Are Statistics"
AUTHOR_RUN = "[Author] et al."
TECTONIC = os.environ.get("TECTONIC", "tectonic")      # LaTeX engine for the TikZ figure


# ----------------------------------------------------------------- reference document
def make_reference(unzipped):
    """Turn the unzipped .docm template into a macro-free .docx reference document."""
    src = Path(unzipped)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "ref"
        shutil.copytree(src, d)
        for p in ("customUI", "word/vbaProject.bin", "word/vbaData.xml",
                  "word/_rels/vbaProject.bin.rels", "word/charts"):
            q = d / p
            shutil.rmtree(q) if q.is_dir() else q.unlink(missing_ok=True)
        ct = (d / "[Content_Types].xml").read_text(encoding="utf-8-sig")
        ct = ct.replace("application/vnd.ms-word.document.macroEnabled.main+xml",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
        ct = re.sub(r'\s*<Default Extension="(bin|ICO)"[^>]*/>', "", ct)
        ct = re.sub(r'\s*<Override PartName="/word/(vbaData|charts/chart1)\.xml"[^>]*/>', "", ct)
        ct = ct.replace('ContentType="image/.png"', 'ContentType="image/png"')
        (d / "[Content_Types].xml").write_text(ct, encoding="utf-8")
        rels = (d / "_rels/.rels").read_text(encoding="utf-8-sig")
        rels = re.sub(r'<Relationship [^>]*customUI[^>]*/>', "", rels)
        (d / "_rels/.rels").write_text(rels, encoding="utf-8")
        drels = (d / "word/_rels/document.xml.rels").read_text(encoding="utf-8-sig")
        drels = re.sub(r'\s*<Relationship [^>]*(vbaProject|charts/chart1)[^>]*/>', "", drels)
        (d / "word/_rels/document.xml.rels").write_text(drels, encoding="utf-8")
        doc = (d / "word/document.xml").read_text(encoding="utf-8-sig")
        sect = re.findall(r"<w:sectPr\b.*?</w:sectPr>", doc, re.S)[-1]
        body_start = doc.index("<w:body>") + len("<w:body>")
        doc = doc[:body_start] + "<w:p/>" + sect + "</w:body></w:document>"
        (d / "word/document.xml").write_text(doc, encoding="utf-8")
        for h in d.glob("word/header*.xml"):          # running heads: short title / authors
            x = h.read_text(encoding="utf-8-sig")
            x = x.replace(">F. Author and S. Author<", ">" + AUTHOR_RUN + "<")
            x = x.replace(">Contribution Title (shortened if too long) <", ">" + SHORT_TITLE + " <")
            h.write_text(x, encoding="utf-8")
        REF.unlink(missing_ok=True)
        with zipfile.ZipFile(REF, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(d).as_posix())
    print("wrote", REF)


# ----------------------------------------------------------------- LaTeX preprocessing
def arg(s, i):
    """Return (content, end) of the brace group starting at s[i] == '{'."""
    assert s[i] == "{", s[i:i + 30]
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{" and s[j - 1] != "\\":
            depth += 1
        elif s[j] == "}" and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    raise ValueError("unbalanced braces")


def render_tikz(tikz, preamble_lines, name):
    """Render one tikzpicture to figures/<name>.png (600 dpi) with tectonic."""
    FIG.mkdir(exist_ok=True)
    doc = ("\\documentclass[border=4pt]{standalone}\n\\usepackage{amsmath,amssymb}\n\\usepackage{tikz}\n"
           + "\n".join(preamble_lines) + "\n\\begin{document}\n" + tikz + "\n\\end{document}\n")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "f.tex").write_text(doc)
        r = subprocess.run([TECTONIC, "-X", "compile", "f.tex"], cwd=tmp, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])
        subprocess.run(["pdftoppm", "-png", "-r", "600", "-singlefile", "f.pdf", "f"], cwd=tmp, check=True)
        shutil.copy(Path(tmp) / "f.png", FIG / f"{name}.png")
    return f"{name}.png"


def algorithmic_lines(body):
    """Flatten an algorithmic environment into numbered, indented lines (LaTeX math kept)."""
    body = re.sub(r"\\Call\{([^}]*)\}\{([^}]*)\}", r"\\textsc{\1}(\2)", body)
    toks = re.split(r"(\\(?:State|Require|Ensure|If|ElsIf|Else|EndIf|For|EndFor|ForAll|While|EndWhile|Loop|EndLoop|Return|Comment)\b)", body)
    lines, depth, cur = [], 0, None

    def flush():
        nonlocal cur
        if cur is not None:
            lines.append(cur)
        cur = None

    i = 0
    while i < len(toks):
        t = toks[i]
        if t.startswith("\\") and t[1:] in ("State", "Require", "Ensure", "If", "ElsIf", "Else", "EndIf", "For",
                                            "EndFor", "ForAll", "While", "EndWhile", "Loop", "EndLoop",
                                            "Return", "Comment"):
            kw = t[1:]
            rest = toks[i + 1] if i + 1 < len(toks) else ""
            text = rest
            cond = ""
            if kw in ("If", "ElsIf", "For", "ForAll", "While", "Comment") and rest.lstrip().startswith("{"):
                k = len(rest) - len(rest.lstrip())
                cond, e = arg(rest, k)
                text = rest[e:]
            text = text.strip()
            if kw == "Comment":
                cur = (cur[0], cur[1] + r" \hfill\emph{$\triangleright$ " + cond + "}", cur[2]) if cur else (depth, r"\emph{$\triangleright$ " + cond + "}", True)
            else:
                flush()
                if kw in ("EndIf", "EndFor", "EndWhile", "EndLoop"):
                    depth -= 1
                    cur = (depth, r"\textbf{end " + kw[3:].lower().replace("for", "for").replace("loop", "loop") + "}", True)
                elif kw == "Require":
                    cur = (depth, r"\textbf{Input:} " + text, False)
                    text = ""
                elif kw == "Ensure":
                    cur = (depth, r"\textbf{Output:} " + text, False)
                    text = ""
                elif kw == "State":
                    cur = (depth, text, True)
                    text = ""
                elif kw == "Return":
                    cur = (depth, r"\textbf{return} " + text, True)
                    text = ""
                elif kw in ("If", "ElsIf"):
                    if kw == "ElsIf":
                        depth -= 1
                    cur = (depth, (r"\textbf{if} " if kw == "If" else r"\textbf{else if} ") + cond + r" \textbf{then}", True)
                    depth += 1
                elif kw == "Else":
                    depth -= 1
                    cur = (depth, r"\textbf{else}", True)
                    depth += 1
                elif kw in ("For", "ForAll"):
                    cur = (depth, r"\textbf{for} " + cond + r" \textbf{do}", True)
                    depth += 1
                elif kw == "While":
                    cur = (depth, r"\textbf{while} " + cond + r" \textbf{do}", True)
                    depth += 1
                elif kw == "Loop":
                    cur = (depth, r"\textbf{loop}", True)
                    depth += 1
                if text:              # e.g. "\If{c} \State x" keeps text after the keyword
                    flush()
                    cur = (depth, text, True)
            i += 2
            continue
        i += 1
    flush()
    out, n = [], 0
    for d, txt, numbered in lines:
        txt = re.sub(r"\s+", " ", txt).strip()
        txt = re.sub(r"\$[^$]*\$", lambda m: m.group(0).replace("\\textsc{", "\\mathrm{"), txt)  # OMML has no \textsc
        if not txt:
            continue
        if numbered:
            n += 1
            label = f"{n}:"
        else:
            label = ""
        out.append((label, d, txt))
    return out


def preprocess(tex):
    pre = tex[:tex.index("\\begin{document}")]
    title = re.search(r"\\title\[[^\]]*\]", tex)
    title_text, _ = arg(tex, title.end())
    abs_i = tex.index("\\abstract{") + len("\\abstract")
    abstract, _ = arg(tex, abs_i)
    abstract = re.sub(r"\\textbf\{(Purpose|Methods|Results|Conclusion):\}\s*", "", abstract)
    kw_i = tex.index("\\keywords{") + len("\\keywords")
    keywords, _ = arg(tex, kw_i)
    body = tex[tex.index("\\section{Introduction}"):tex.index("\\backmatter")]
    back = tex[tex.index("\\backmatter"):tex.index("\\bibliography{")]

    # TikZ figure -> PNG
    tikz_pre = [l for l in pre.splitlines() if l.startswith(("\\usetikzlibrary", "\\newcommand"))]
    def tikz_sub(m):
        return "\\includegraphics[width=\\linewidth]{" + render_tikz(m.group(0), tikz_pre, "fig0_architecture") + "}"
    body = re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", tikz_sub, body, flags=re.S)

    # algorithms -> captioned, numbered program-code blocks (styled by the Lua filter)
    alg_n = 0
    def alg_sub(m):
        nonlocal alg_n
        alg_n += 1
        block = m.group(0)
        cap_i = block.index("\\caption") + len("\\caption")
        cap, _ = arg(block, cap_i)
        lab = re.search(r"\\label\{([^}]*)\}", block)
        algbody = re.search(r"\\begin\{algorithmic\}(?:\[\d+\])?(.*?)\\end\{algorithmic\}", block, re.S).group(1)
        rows = []
        for label, d, txt in algorithmic_lines(algbody):
            rows.append("\\begin{algline}" + (label + "~" if label else "") + "~~~~" * d + txt + "\\end{algline}")
        head = "\\begin{algcaption}\\textbf{Algorithm " + str(alg_n) + ".} " + re.sub(r"\\label\{[^}]*\}", "", cap) + "\\end{algcaption}"
        return "\\begin{algorithmblock}" + head + "\n" + "\n".join(rows) + "\\end{algorithmblock}", (lab.group(1) if lab else None, alg_n)
    algs = {}
    def alg_wrap(m):
        s, (lab, n) = alg_sub(m)
        if lab:
            algs[lab] = n
        return s
    body = re.sub(r"\\begin\{algorithm\}(?:\[[^\]]*\])?.*?\\end\{algorithm\}", alg_wrap, body, flags=re.S)
    for lab, n in algs.items():                       # pandoc cannot resolve refs to our blocks
        body = body.replace("\\ref{" + lab + "}", str(n))

    # tabularx -> tabular (pandoc reads p{} widths)
    def tabx(m):
        spec = re.sub(r">\{[^}]*\}", "", m.group(1))
        cols = re.findall(r"X|p\{[^}]*\}|[lcr]", spec)
        return "\\begin{tabular}{" + "".join("p{6cm}" if c == "X" else c for c in cols) + "}"
    body = re.sub(r"\\begin\{tabularx\}\{[^}]*\}\{((?:[^{}]|\{[^{}]*\})*)\}", tabx, body)
    body = body.replace("\\end{tabularx}", "\\end{tabular}")
    body = re.sub(r"\\renewcommand\{\\arraystretch\}\{[^}]*\}|\\setlength\{\\tabcolsep\}\{[^}]*\}", "", body)

    # numbered display equations: pandoc drops the number, so put it in the formula
    eq_n = 0
    eqs = {}
    def eq_sub(m):
        nonlocal eq_n
        eq_n += 1
        inner = m.group(1)
        lab = re.search(r"\\label\{([^}]*)\}", inner)
        if lab:
            eqs[lab.group(1)] = eq_n
        inner = re.sub(r"\\label\{[^}]*\}", "", inner).strip()
        return "\\[" + inner + "\\qquad\\qquad(" + str(eq_n) + ")\\]"
    body = re.sub(r"\\begin\{equation\}(.*?)\\end\{equation\}", eq_sub, body, flags=re.S)
    for lab, n in eqs.items():
        body = re.sub(r"\\eqref\{" + re.escape(lab) + r"\}", f"({n})", body)
        body = body.replace("\\ref{" + lab + "}", str(n))

    # contributions list with \item[C1] labels -> run-in labelled paragraphs
    def labelled(m):
        items = re.split(r"\\item\[([^\]]*)\]", m.group(1))[1:]
        return "\n".join("\\begin{contribution}\\textbf{" + items[k] + "} " + items[k + 1].strip() + "\\end{contribution}"
                         for k in range(0, len(items), 2))
    body = re.sub(r"\\begin\{enumerate\}\s*(\\item\[.*?)\\end\{enumerate\}", labelled, body, flags=re.S)

    # LNCS run-in headings: \paragraph{X} -> bold run-in text
    body = re.sub(r"\\paragraph\{([^}]*)\}\s*", r"\\textbf{\1} ", body)
    body = body.replace("\\\\[2pt]", "\n\n").replace("\\hfill", "")

    # back matter (LNCS: run-in "Acknowledgments." and "Disclosure of Interests.")
    def bm(name):
        m = re.search(r"\\bmhead\{" + name + r"\}", back)
        if not m:
            return ""
        nxt = back.find("\\bmhead", m.end())
        nxt2 = back.find("\\section*", m.end())
        end = min(x for x in (nxt, nxt2, len(back)) if x >= 0)
        return back[m.end():end].strip()
    decl = re.search(r"\\begin\{itemize\}(.*?)\\end\{itemize\}", back, re.S).group(1)
    items = [x.strip() for x in decl.split("\\item") if x.strip()]
    backtex = ("\\begin{acknowledgments}\\textbf{Acknowledgments.} " + bm("Acknowledgements") + "\\end{acknowledgments}\n\n"
               "\\begin{acknowledgments}\\textbf{Supplementary information.} " + bm("Supplementary information") + "\\end{acknowledgments}\n\n"
               "\\begin{acknowledgments}\\textbf{Disclosure of Interests.} The declarations required by Springer are listed below.\\end{acknowledgments}\n\n"
               + "\n\n".join("\\begin{declaration}" + it + "\\end{declaration}" for it in items) + "\n\n")

    macros = "\n".join(l for l in pre.splitlines() if l.startswith("\\newcommand"))
    macros += "\n\\newtheorem{theorem}{Theorem}\n\\newtheorem{proposition}[theorem]{Proposition}\n" \
              "\\newtheorem{assumption}{Assumption}\n\\newtheorem{definition}{Definition}\n"
    front = ("\\begin{papertitle}" + title_text + "\\end{papertitle}\n\n"
             "\\begin{author}{[}Author Name{]}\\textsuperscript{1}\\end{author}\n\n"
             "\\begin{address}\\textsuperscript{1} [Department], [Organization], [City], [Country]\\end{address}\n\n"
             "\\begin{email}{[}corresponding author e-mail{]}\\end{email}\n\n"
             "\\begin{abstractblock}\\textbf{Abstract.} " + re.sub(r"\s*\n\s*", " ", abstract.strip()) + "\\end{abstractblock}\n\n"
             "\\begin{keywords}\\textbf{Keywords:} " + " $\\cdot$ ".join(k.strip() for k in keywords.split(",")) + "\\end{keywords}\n\n")
    doc = ("\\documentclass{article}\n\\usepackage{amsmath,amssymb,amsthm,graphicx,booktabs}\n" + macros +
           "\n\\begin{document}\n" + front + body + backtex + "\\section*{References}\n\\end{document}\n")
    return doc


# ----------------------------------------------------------------- post-processing
PSTYLE = {
    "Title": "papertitle", "FirstParagraph": "p1a", "BodyText": "Normal", "Compact": "p1a",
    "ImageCaption": "figurecaption", "TableCaption": "tablecaption", "CaptionedFigure": "image",
    "Figure": "image", "Bibliography": "referenceitem", "Heading1": "heading1", "Heading2": "heading2",
    "Heading3": "heading3", "BlockText": "Normal", "heading 1": "heading1", "heading 2": "heading2",
}


def postprocess(path):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "x"
        with zipfile.ZipFile(path) as z:
            z.extractall(d)
        docp = d / "word/document.xml"
        x = docp.read_text(encoding="utf-8")
        styles = (d / "word/styles.xml").read_text(encoding="utf-8")
        ids = set(re.findall(r'w:styleId="([^"]+)"', styles))

        def ps(m):
            v = m.group(1)
            v = PSTYLE.get(v, v)
            return f'<w:pStyle w:val="{v}"/>' if v in ids else '<w:pStyle w:val="Normal"/>'
        x = re.sub(r'<w:pStyle w:val="([^"]+)"\s*/>', ps, x)

        paras = re.split(r"(<w:p>|<w:p [^>]*>)", x)
        # unnumbered headings (References, ...): pandoc marks them; LNCS heading1 numbers itself
        out = []
        prev_is_heading = False
        for k, chunk in enumerate(paras):
            if '<w:pStyle w:val="heading1"/>' in chunk and re.search(r">(References)<", chunk):
                chunk = chunk.replace('<w:pStyle w:val="heading1"/>',
                                      '<w:pStyle w:val="heading1"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr><w:ind w:left="0" w:firstLine="0"/>')
            # first paragraph after a heading or figure/table caption: p1a (no indent), as LNCS asks
            if prev_is_heading and '<w:pStyle w:val="Normal"/>' in chunk.split("</w:pPr>")[0]:
                chunk = chunk.replace('<w:pStyle w:val="Normal"/>', '<w:pStyle w:val="p1a"/>', 1)
            if chunk.startswith("<w:p"):
                pass
            elif "<w:pPr>" in chunk or "</w:p>" in chunk:
                head = chunk.split("</w:pPr>")[0]
                prev_is_heading = any(f'w:val="{s}"' in head for s in ("heading1", "heading2", "heading3", "figurecaption", "tablecaption", "image", "programcode", "algcaption"))
            out.append(chunk)
        x = "".join(out)
        # table captions above tables are already the pandoc order; make tables use LNCS's thin rules
        x = re.sub(r'<w:jc w:val="start"\s*/>(<w:tblCaption)', r'\1', x)     # centre tables, in schema order
        x = re.sub(r'(<w:tblW [^>]*/>)', r'\1<w:jc w:val="center"/>', x)
        docp.write_text(x, encoding="utf-8")
        ctp = d / "[Content_Types].xml"
        ct = ctp.read_text(encoding="utf-8")
        for ext, mime in (("png", "image/png"), ("jpeg", "image/jpeg"), ("jpg", "image/jpeg")):
            if f'Extension="{ext}"' not in ct and list(d.glob(f"word/media/*.{ext}")):
                ct = ct.replace("<Default ", f'<Default Extension="{ext}" ContentType="{mime}"/><Default ', 1)
        ctp.write_text(ct, encoding="utf-8")
        if 'w:styleId="Table"' not in styles:          # booktabs-like rules: top, below header, bottom
            rule = '<w:{0} w:val="single" w:sz="{1}" w:space="0" w:color="000000"/>'
            st = ('<w:style w:type="table" w:customStyle="1" w:styleId="Table"><w:name w:val="Table"/>'
                  '<w:basedOn w:val="Normal Table"/><w:pPr><w:ind w:firstLine="0"/><w:jc w:val="left"/></w:pPr>'
                  '<w:rPr><w:sz w:val="18"/></w:rPr><w:tblPr><w:tblBorders>' + rule.format("top", 8)
                  + rule.format("bottom", 8) + '</w:tblBorders><w:tblCellMar><w:left w:w="57" w:type="dxa"/>'
                  '<w:right w:w="57" w:type="dxa"/></w:tblCellMar></w:tblPr>'
                  '<w:tblStylePr w:type="firstRow"><w:tcPr><w:tcBorders>' + rule.format("bottom", 4)
                  + '</w:tcBorders></w:tcPr></w:tblStylePr></w:style>')
            styles = styles.replace("</w:styles>", st + "</w:styles>")
            (d / "word/styles.xml").write_text(styles, encoding="utf-8")
        path.unlink()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(d).as_posix())


def build():
    tex = SRC.read_text()
    doc = preprocess(tex)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp) / "m.tex"
        t.write_text(doc)
        res = [str(ROOT / "figures"), str(FIG)]
        subprocess.run(["pandoc", str(t), "-f", "latex", "-t", "docx", "-o", str(OUT),
                        "--reference-doc", str(REF), "--citeproc", "--bibliography", str(BIB),
                        "--csl", str(CSL), "--lua-filter", str(FILTER),
                        "--resource-path", os.pathsep.join(res)], check=True)
    postprocess(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "reference":
        make_reference(sys.argv[2])
    else:
        build()
