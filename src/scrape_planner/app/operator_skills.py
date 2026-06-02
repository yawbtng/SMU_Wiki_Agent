"""Registry of operator Pi skills launchable via the jobs API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.data_root import repo_root


@dataclass(frozen=True)
class OperatorSkillSpec:
    skill_id: str
    title: str
    description: str
    skill_dir: str
    script_name: str
    report_glob: str
    session_prefix: str


def repo_skill_dir(skill_id: str) -> Path:
    return repo_root() / ".pi" / "skills" / skill_id


OPERATOR_SKILLS: dict[str, OperatorSkillSpec] = {
    "site-discovery": OperatorSkillSpec(
        skill_id="site-discovery",
        title="Site URL discovery",
        description="Discover sitemap URLs for a site and write discovered_urls.json.",
        skill_dir="site-discovery",
        script_name="discover_site.sh",
        report_glob="site-discovery-*.json",
        session_prefix="discover",
    ),
    "site-url-curation": OperatorSkillSpec(
        skill_id="site-url-curation",
        title="Approved URL curation",
        description="Curate approved_urls.md from discovery pool using an operator prompt.",
        skill_dir="site-url-curation",
        script_name="curate_urls.sh",
        report_glob="site-url-curation-*.json",
        session_prefix="curate",
    ),
    "llm-wiki-noninteractive": OperatorSkillSpec(
        skill_id="llm-wiki-noninteractive",
        title="LLM wiki build",
        description="Compile wiki pages, lint, and rebuild hybrid index.",
        skill_dir="llm-wiki-noninteractive",
        script_name="build_wiki.sh",
        report_glob="wiki-build-*.json",
        session_prefix="wiki",
    ),
}


def list_operator_skills() -> list[dict[str, str]]:
    return [
        {
            "id": spec.skill_id,
            "title": spec.title,
            "description": spec.description,
            "script": spec.script_name,
        }
        for spec in OPERATOR_SKILLS.values()
    ]


def get_operator_skill(skill_id: str) -> OperatorSkillSpec:
    spec = OPERATOR_SKILLS.get(skill_id.strip())
    if not spec:
        known = ", ".join(sorted(OPERATOR_SKILLS))
        raise KeyError(f"Unknown skill `{skill_id}`. Known skills: {known}")
    return spec


def skill_script_path(spec: OperatorSkillSpec) -> Path:
    return repo_skill_dir(spec.skill_dir) / "scripts" / spec.script_name
