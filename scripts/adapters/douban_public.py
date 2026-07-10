from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import urljoin


CHART_URL = "https://movie.douban.com/chart"


class PageStateError(ValueError):
    pass


class _ChartParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.content_seen = False
        self.empty_seen = False
        self._capture: str | None = None
        self._item_tag = ""
        self._item_tag_depth = 0
        self._stack: list[str] = []
        self._content_level: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self._stack.append(tag)
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if values.get("id") == "content":
            self.content_seen = True
            self._content_level = len(self._stack)
        if "empty" in classes and self._content_level is not None and len(self._stack) >= self._content_level:
            self.empty_seen = True
        if tag in {"div", "tr"} and "item" in classes:
            self.current = {"title": "", "url": "", "rating": "", "rating_count": "", "summary": ""}
            self._item_tag = tag
            self._item_tag_depth = 1
            return
        if self.current is None:
            return
        if tag == self._item_tag:
            self._item_tag_depth += 1
        if tag == "a" and "/subject/" in (values.get("href") or ""):
            self.current["url"] = values["href"] or ""
            self._capture = "title"
        elif tag == "span" and "rating_nums" in classes:
            self._capture = "rating"
        elif tag == "span" and "pl" in classes:
            self._capture = "rating_count"
        elif tag == "p":
            self._capture = "summary"

    def handle_endtag(self, tag: str) -> None:
        if tag == self._item_tag and self.current is not None:
            self._item_tag_depth -= 1
            if self._item_tag_depth == 0:
                item = self.current
                self.current = None
                self._item_tag = ""
                self._capture = None
                self.records.append(item)
        elif tag in {"a", "span", "p"}:
            self._capture = None
        if self._content_level is not None and len(self._stack) == self._content_level and tag == self._stack[-1]:
            self._content_level = None
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self.current is not None and self._capture:
            self.current[self._capture] = f"{self.current[self._capture]}{data}".strip()


def parse_movie_chart(html: str, *, limit: int) -> tuple[list[dict[str, Any]], str]:
    parser = _ChartParser()
    parser.feed(html)
    if not parser.content_seen:
        raise PageStateError("page_not_ready: chart content container is missing")
    if not parser.records:
        if parser.empty_seen:
            return [], "empty"
        raise PageStateError("page_not_ready: chart items are missing")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(parser.records[:limit], start=1):
        url = urljoin(CHART_URL, str(item["url"]))
        subject = re.search(r"/subject/(\d+)", url)
        rating = re.search(r"\d+(?:\.\d+)?", str(item["rating"]))
        votes = re.search(r"\d+", str(item["rating_count"]).replace(",", ""))
        year = re.search(r"(?:19|20)\d{2}", str(item["summary"]))
        title = re.sub(r"\s+", " ", str(item["title"])).strip()
        if not (subject and title and rating and votes and year):
            raise PageStateError("field_gap: movie ranking entry misses required semantic fields")
        records.append({"id": subject.group(1), "url": url, "title": title, "rank": index, "rating": float(rating.group()), "rating_count": int(votes.group()), "summary": re.sub(r"\s+", " ", str(item["summary"])).strip(), "year": year.group()})
    return records, "items"
