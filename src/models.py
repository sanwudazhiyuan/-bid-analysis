from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Paragraph:
    index: int
    text: str
    style: Optional[str] = None
    is_table: bool = False
    table_data: Optional[list] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaggedParagraph:
    index: int
    text: str
    section_title: Optional[str] = None
    section_level: int = 0
    tags: list[str] = field(default_factory=list)
    table_data: Optional[list] = None

    def to_dict(self) -> dict:
        return asdict(self)
