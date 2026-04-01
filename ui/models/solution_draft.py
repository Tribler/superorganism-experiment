from dataclasses import dataclass

from ui.constants import (
    SOLUTION_TITLE_MIN_LENGTH,
    SOLUTION_TITLE_MAX_LENGTH,
    SOLUTION_DESCRIPTION_MIN_LENGTH,
    SOLUTION_DESCRIPTION_MAX_LENGTH
)


@dataclass(frozen=True)
class SolutionDraft:
    title: str
    description: str

    def normalized(self) -> "SolutionDraft":
        return SolutionDraft(
            title=self.title.strip(),
            description=self.description.strip(),
        )

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}

        title = self.title.strip()
        description = self.description.strip()

        if not title:
            errors["title"] = "Title is required."
        elif len(title) < SOLUTION_TITLE_MIN_LENGTH:
            errors["title"] = f"Title must be at least {SOLUTION_TITLE_MIN_LENGTH} characters."
        elif len(title) > SOLUTION_TITLE_MAX_LENGTH:
            errors["title"] = f"Title must be at most {SOLUTION_TITLE_MAX_LENGTH} characters."

        if not description:
            errors["description"] = "Description is required."
        elif len(description) < SOLUTION_DESCRIPTION_MIN_LENGTH:
            errors["description"] = (
                f"Description must be at least {SOLUTION_DESCRIPTION_MIN_LENGTH} characters."
            )
        elif len(description) > SOLUTION_DESCRIPTION_MAX_LENGTH:
            errors["description"] = (
                f"Description must be at most {SOLUTION_DESCRIPTION_MAX_LENGTH} characters."
            )

        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()