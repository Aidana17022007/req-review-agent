"""v9: понятные ошибки на «сломанных» входных файлах — что случилось, что сделать, код возврата, без трейсбека."""
from __future__ import annotations


class DocumentError(ValueError):
    """Проблема входного документа (не агента): сообщение и подсказка — по-русски, для показа пользователю как есть.

    code — код возврата review.py: 2 — файл не найден / формат не поддерживается, 3 — содержимое не читается или в нём
    нет требований."""

    def __init__(self, message: str, hint: str, code: int = 3, kind: str = "document"):
        super().__init__(message)
        self.message, self.hint, self.code, self.kind = message, hint, code, kind

    def __str__(self) -> str:
        return f"{self.message} Что сделать: {self.hint}"


SAVE_AS = "откройте файл в Word и сохраните как .docx (Файл → Сохранить как) или как PDF с текстом"
