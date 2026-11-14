"""Loaders: turn a portfolio folder (or uploaded files) into typed documents with metadata.

Every document carries: owner (tenant), persona, type, title, project, skills, date,
client_industry, outcome (proposals), source path. Project names are resolved through an alias
map (case-study titles <-> repo names <-> product names in READMEs) because the corpus describes the
same project several ways.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from rag.skills import extract_skills

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".sql", ".r", ".ipynb"}


@dataclass
class Doc:
    evidence_id: str
    owner: str
    persona: str
    type: str  # cv | case_study | blog_post | readme | code | review | proposal | upload
    title: str
    text: str
    project: str | None = None
    skills: list[str] = field(default_factory=list)
    date: str | None = None
    client_industry: str | None = None
    outcome: str | None = None  # won | replied | ignored (proposals only)
    source: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha1((self.text + json.dumps(self.extra, sort_keys=True)).encode()).hexdigest()[:16]

    def to_dict(self):
        return asdict(self) | {"content_hash": self.content_hash}


def _frontmatter(md: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", md, re.S)
    if not m:
        return {}, md
    return yaml.safe_load(m.group(1)) or {}, md[m.end():]


def read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)


class AliasMap:
    """Maps any name a project goes by (title, product name, repo) to its canonical title."""

    def __init__(self):
        self.names: dict[str, str] = {}

    def add(self, alias: str, title: str):
        if alias and title:
            self.names[alias.lower()] = title

    def find_in(self, text: str) -> str | None:
        low = text.lower()
        hits = [(len(a), t) for a, t in self.names.items() if len(a) > 4 and a in low]
        return max(hits)[1] if hits else None


_STOP = set("the a an and or of to for in on our we with that this is it be by from as at you your i my me".split())


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in _STOP}


def resolve_by_overlap(text: str, case_studies: dict[str, str], threshold: float = 0.35) -> str | None:
    """Entity resolution fallback: the case study whose wording overlaps most (overlap coefficient)."""
    t = _terms(text)
    best, score = None, 0.0
    for title, body in case_studies.items():
        b = _terms(body[:600])
        s = len(t & b) / max(1, min(len(t), len(b)))
        if s > score:
            best, score = title, s
    return best if score >= threshold else None


def load_persona(folder: Path, owner: str | None = None) -> list[Doc]:
    persona = folder.name
    owner = owner or persona
    profile = json.loads((folder / "profile.json").read_text(encoding="utf-8")) if (folder / "profile.json").exists() else {}
    docs: list[Doc] = []
    aliases = AliasMap()
    stem_by_title: dict[str, str] = {}

    # case studies first: they define canonical project titles
    blogs = []
    for md_path in sorted((folder / "case_studies").glob("*.md")):
        fm, body = _frontmatter(md_path.read_text(encoding="utf-8"))
        if not fm:
            blogs.append(md_path)
            continue
        title = fm.get("project") or md_path.stem
        stem_by_title[title] = md_path.stem
        aliases.add(title, title)
        docs.append(Doc(f"{persona}-cs-{md_path.stem}", owner, persona, "case_study", title, body.strip(),
                        project=title, skills=sorted(set(fm.get("skills", [])) | set(extract_skills(body))),
                        date=str(fm.get("date", "")), client_industry=fm.get("client_industry"),
                        source=str(md_path.relative_to(folder))))

    cs_bodies = {d.title: d.text for d in docs}
    # repos: profile.json maps repo -> project title; README first line names the product
    for repo, title in profile.get("repos", {}).items():
        rdir = folder / "repos" / repo
        if not rdir.exists():
            continue
        aliases.add(repo, title)
        readme = (rdir / "README.md").read_text(encoding="utf-8") if (rdir / "README.md").exists() else ""
        m = re.search(r"^(.+?) - ", readme.split("\n\n", 2)[1] if readme.count("\n\n") >= 1 else "", re.M)
        if m:
            aliases.add(m.group(1).strip(), title)
        slug = stem_by_title.get(title, repo)
        if readme:
            docs.append(Doc(f"{persona}-readme-{slug}", owner, persona, "readme", f"{repo} README", readme,
                            project=title, skills=extract_skills(readme), source=f"repos/{repo}/README.md"))
        for code in sorted(p for p in rdir.rglob("*") if p.suffix.lower() in CODE_EXT):
            text = code.read_text(encoding="utf-8", errors="ignore")
            docs.append(Doc(f"{persona}-code-{slug}", owner, persona, "code", f"{repo}/{code.relative_to(rdir).as_posix()}",
                            text, project=title, skills=extract_skills(text, code=True),
                            source=str(code.relative_to(folder).as_posix())))

    for md_path in blogs:
        text = md_path.read_text(encoding="utf-8")
        title = aliases.find_in(text) or resolve_by_overlap(text, cs_bodies)
        stem = md_path.stem.removesuffix("-blog")
        m = re.search(r"\*Posted (\d{4}-\d{2})\*", text)
        docs.append(Doc(f"{persona}-blog-{stem}", owner, persona, "blog_post", text.splitlines()[0].lstrip("# "), text,
                        project=title, skills=extract_skills(text), date=m.group(1) if m else None,
                        source=str(md_path.relative_to(folder))))

    if (folder / "cv.pdf").exists():
        text = read_pdf(folder / "cv.pdf")
        docs.append(Doc(f"{persona}-cv", owner, persona, "cv", "Curriculum vitae", text, skills=extract_skills(text),
                        source="cv.pdf"))

    if (folder / "reviews.json").exists():
        for r in json.loads((folder / "reviews.json").read_text(encoding="utf-8")):
            docs.append(Doc(r["review_id"], owner, persona, "review", f"Client review: {r['project']}",
                            f"Client review ({r['rating']}/5) for {r['project']}: {r['text']}",
                            project=aliases.find_in(r["project"]) or r["project"], skills=extract_skills(r["text"]),
                            date=r.get("date"), client_industry=r.get("client_industry"), source="reviews.json",
                            extra={"rating": r["rating"]}))

    if (folder / "proposals.jsonl").exists():
        for line in (folder / "proposals.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            docs.append(Doc(p["proposal_id"], owner, persona, "proposal", f"Past proposal: {p['job_title']}",
                            p["text"], project=aliases.find_in(p["text"]) or resolve_by_overlap(p["text"], cs_bodies, 0.45), skills=extract_skills(p["text"]),
                            date=p.get("date"), outcome=p.get("outcome"), source="proposals.jsonl",
                            extra={"job_category": p.get("job_category"), "bid_usd": p.get("bid_usd")}))
    return docs


def load_upload(path: Path, owner: str, persona: str, meta: dict) -> Doc:
    """A file the user added in the UI (PDF, Markdown, text or code)."""
    text = read_pdf(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8", errors="ignore")
    fm, body = _frontmatter(text) if path.suffix.lower() == ".md" else ({}, text)
    is_code = path.suffix.lower() in CODE_EXT
    digest = hashlib.sha1(text.encode()).hexdigest()[:10]
    return Doc(f"{owner}-upload-{digest}", owner, persona, meta.get("type") or ("code" if is_code else "upload"),
               meta.get("title") or fm.get("project") or path.stem, body,
               project=meta.get("project") or fm.get("project"),
               skills=sorted(set(fm.get("skills", [])) | set(extract_skills(body, code=is_code))),
               date=meta.get("date") or (str(fm["date"]) if fm.get("date") else None),
               client_industry=meta.get("client_industry") or fm.get("client_industry"),
               outcome=meta.get("outcome"), source=path.name)
