import QtQuick 2.12

MouseArea {
    id: grip
    property int edge: 0
    hoverEnabled: true
    cursorShape: edge === Qt.LeftEdge || edge === Qt.RightEdge ? Qt.SizeHorCursor
        : edge === Qt.TopEdge || edge === Qt.BottomEdge ? Qt.SizeVerCursor
        : edge === (Qt.LeftEdge | Qt.TopEdge) || edge === (Qt.RightEdge | Qt.BottomEdge) ? Qt.SizeFDiagCursor
        : Qt.SizeBDiagCursor
    onPressed: window.beginResize(edge, mapToGlobal(mouse.x, mouse.y))
    onPositionChanged: if (pressed) window.moveResize(mapToGlobal(mouse.x, mouse.y))
    onReleased: window.resizing = false
}
