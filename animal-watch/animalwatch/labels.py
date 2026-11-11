"""Romanian names and ntfy emoji tags for COCO animal classes."""

RO = {
    "bird": "Pasăre", "cat": "Pisică", "dog": "Câine", "horse": "Cal", "sheep": "Oaie",
    "cow": "Vacă", "elephant": "Elefant", "bear": "Urs", "zebra": "Zebră", "giraffe": "Girafă",
}
# ntfy converts these shortcodes to emoji
TAGS = {
    "bird": "bird", "cat": "cat", "dog": "dog", "horse": "horse", "sheep": "sheep",
    "cow": "cow", "elephant": "elephant", "bear": "bear", "zebra": "zebra", "giraffe": "giraffe",
}
COCO_ANIMALS = list(RO)


def ro(cls: str) -> str:
    return RO.get(cls, cls.capitalize())
