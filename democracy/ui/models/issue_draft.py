from dataclasses import dataclass

from constants import ISSUE_TITLE_MIN_LENGTH, ISSUE_TITLE_MAX_LENGTH, ISSUE_DESCRIPTION_MIN_LENGTH, \
    ISSUE_DESCRIPTION_MAX_LENGTH


@dataclass(frozen=True)
class IssueDraft:
    title: str
    description: str

    def normalized(self) -> "IssueDraft":
        return IssueDraft(
            title=self.title.strip(),
            description=self.description.strip(),
        )

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}

        title = self.title.strip()
        description = self.description.strip()

        if not title:
            errors["title"] = "Title is required."
        elif len(title) < ISSUE_TITLE_MIN_LENGTH:
            errors["title"] = f"Title must be at least {ISSUE_TITLE_MIN_LENGTH} characters."
        elif len(title) > ISSUE_TITLE_MAX_LENGTH:
            errors["title"] = f"Title must be at most {ISSUE_TITLE_MAX_LENGTH} characters."

        if not description:
            errors["description"] = "Description is required."
        elif len(description) < ISSUE_DESCRIPTION_MIN_LENGTH:
            errors["description"] = (
                f"Description must be at least {ISSUE_DESCRIPTION_MIN_LENGTH} characters."
            )
        elif len(description) > ISSUE_DESCRIPTION_MAX_LENGTH:
            errors["description"] = (
                f"Description must be at most {ISSUE_DESCRIPTION_MAX_LENGTH} characters."
            )

        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()