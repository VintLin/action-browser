from argparse import Namespace
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.adapter_runtime import prepare_task_book, wait_for_page_settle


class FakeBook:
    def __init__(self, session: str, tab: str = "", allow_adopt: bool = True) -> None:
        self.session = session
        self.tab = tab
        self.allow_adopt = allow_adopt
        self.events: list[tuple[str, str]] = []
        self.states = [
            {"href": "https://example.com", "title": "A", "text_length": 1, "height": 10},
            {"href": "https://example.com", "title": "A", "text_length": 2, "height": 10},
            {"href": "https://example.com", "title": "A", "text_length": 2, "height": 10},
            {"href": "https://example.com", "title": "A", "text_length": 2, "height": 10},
        ]

    def use_tab(self, tab_id: str):
        self.events.append(("use-tab", tab_id))
        self.tab = tab_id

    def start(self, url: str, force_new_tab: bool = False):
        self.events.append(("start", f"{url}|force={force_new_tab}|adopt={self.allow_adopt}"))
        self.tab = "fresh-tab"

    def eval(self, script: str, timeout: float = 30.0):
        self.events.append(("eval", self.tab))
        return self.states.pop(0)

    def close_tab(self, tab_id: str):
        self.events.append(("close-tab", tab_id))

    def list_tabs(self):
        self.events.append(("list-tabs", self.tab))
        return [{"tab_id": self.tab}]


def test_prepare_task_book_uses_explicit_tab_without_adopt() -> None:
    args = Namespace(session="s1", tab="leased-tab", adopt_running_session=False)

    book = prepare_task_book(args, "https://example.com", FakeBook)

    assert book.events == [("use-tab", "leased-tab")]
    assert book.allow_adopt is False


def test_prepare_task_book_opens_fresh_tab_without_adopt_when_missing_tab() -> None:
    args = Namespace(session="s1", tab="", adopt_running_session=False)

    book = prepare_task_book(args, "https://example.com", FakeBook)

    assert book.events == [("start", "https://example.com|force=True|adopt=False")]
    assert args.tab == "fresh-tab"


def test_prepare_task_book_adopts_when_flag_set() -> None:
    args = Namespace(session="s1", tab="", adopt_running_session=True)

    book = prepare_task_book(args, "https://example.com", FakeBook)

    assert book.events == [("start", "https://example.com|force=True|adopt=True")]
    assert book.allow_adopt is True


def test_prepare_task_book_defaults_to_no_adopt_when_flag_missing() -> None:
    args = Namespace(session="s1", tab="")

    book = prepare_task_book(args, "https://example.com", FakeBook)

    assert book.allow_adopt is False


def test_wait_for_page_settle_polls_until_state_stabilizes() -> None:
    book = FakeBook("s1", "t1")

    wait_for_page_settle(book, timeout_secs=2.0, interval=0.0)

    assert book.events == [("eval", "t1"), ("eval", "t1"), ("eval", "t1"), ("eval", "t1")]


def test_close_temporary_tab_closes_and_verifies_absence() -> None:
    from scripts.adapter_runtime import close_temporary_tab

    book = FakeBook("s1", "main-tab")

    close_temporary_tab(book, "detail-tab")

    assert book.events == [("close-tab", "detail-tab"), ("list-tabs", "main-tab")]
