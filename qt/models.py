# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""QML 用的列表模型。只保存已经取回的数据，不自己请求接口。"""

from PyQt5.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, pyqtSlot, pyqtSignal


class DictListModel(QAbstractListModel):
    rowsChanged = pyqtSignal()

    def __init__(self, roles):
        super().__init__()
        self._roles = {Qt.UserRole + index + 1: QByteArray(name.encode()) for index, name in enumerate(roles)}
        self._names = roles
        self._rows = []

    def roleNames(self):
        return self._roles

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        raw = self._roles.get(role)
        if raw is None:
            return None
        name = bytes(raw).decode()
        value = self._rows[index.row()].get(name)
        if isinstance(value, bool):
            return value
        if value is None:
            return ""
        return value

    def replace(self, rows):
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()
        self.rowsChanged.emit()

    def set_field(self, row, name, value):
        if not (0 <= row < len(self._rows)) or self._rows[row].get(name) == value:
            return
        self._rows[row][name] = value
        index = self.index(row, 0)
        role = next((key for key, raw in self._roles.items() if bytes(raw).decode() == name), None)
        roles = [role] if role is not None else []
        self.dataChanged.emit(index, index, roles)

    def append(self, rows):
        if not rows:
            return
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
        self._rows.extend(dict(row) for row in rows)
        self.endInsertRows()
        self.rowsChanged.emit()

    @pyqtSlot(int, result="QVariantMap")
    def get(self, row):
        if 0 <= row < len(self._rows):
            return dict(self._rows[row])
        return {}
