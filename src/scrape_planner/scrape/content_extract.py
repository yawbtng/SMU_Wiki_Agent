from __future__ import annotations

from bs4 import BeautifulSoup
from markdownify import markdownify as md


def extract_content(html: str) -> tuple[str, str, int, float]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    for tag in soup.select("nav, header, footer, aside, form"):
        tag.decompose()

    body = soup.body or soup
    text = body.get_text(separator=" ", strip=True)
    markdown = md(str(body), heading_style="ATX")

    text_length = len(text)
    links = len(body.find_all("a"))
    words = max(len(text.split()), 1)
    link_density = float(links) / float(words)
    return text, markdown, text_length, link_density

