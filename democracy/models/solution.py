from dataclasses import dataclass


@dataclass
class Solution:
    id: str
    title: str
    description: str
    votes: int
    status_text: str
    highlighted: bool = False