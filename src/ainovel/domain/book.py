"""作品对外信息。书名和简介只住在 meta/book.json。"""

from pydantic import BaseModel, ConfigDict


class BookMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    synopsis: str = ""

    def normalized(self) -> "BookMetadata":
        return BookMetadata(title=self.title.strip(), synopsis=self.synopsis.strip())

    def validate_required(self) -> "BookMetadata":
        book = self.normalized()
        if not book.title:
            raise ValueError("book title is required")
        if not book.synopsis:
            raise ValueError("book synopsis is required")
        return book

    def to_disk(self) -> dict[str, str]:
        book = self.validate_required()
        return {"title": book.title, "synopsis": book.synopsis}

    def render_markdown(self) -> str:
        book = self.validate_required()
        return f"# 《{book.title}》\n\n## 简介\n\n{book.synopsis}\n"
