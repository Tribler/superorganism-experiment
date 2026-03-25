from PyQt6.QtCore import QSortFilterProxyModel, QModelIndex


class IssueFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self._filter_mode = "All"

    def set_search_text(self, text: str) -> None:
        self._search_text = text.lower().strip()
        self.invalidateFilter()

    def set_filter_mode(self, mode: str) -> None:
        self._filter_mode = mode
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True

        title = str(model.index(source_row, 1, source_parent).data() or "").lower()
        creator = str(model.index(source_row, 2, source_parent).data() or "").lower()
        status = str(model.index(source_row, 6, source_parent).data() or "")

        if self._search_text and self._search_text not in title and self._search_text not in creator:
            return False

        if self._filter_mode == "Open" and status != "Open":
            return False
        if self._filter_mode == "Passed" and status != "Passed":
            return False
        if self._filter_mode == "Needs Votes":
            if status == "Passed":
                return False

        return True