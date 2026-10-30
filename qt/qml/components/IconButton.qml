import QtQuick 2.12
import QtQuick.Controls 2.12

Item {
    id: iconButton
    property string kind: ""
    property string iconName: ""
    property string label: ""
    property bool active: false
    property color ink: "#222222"
    property int size: 16
    property string tip: ""
    signal clicked()
    width: 32
    height: 32
    Image {
        visible: iconButton.iconName !== ""
        anchors.centerIn: parent
        width: iconButton.size
        height: iconButton.size
        source: iconButton.iconName !== "" ? "image://icon/" + iconButton.iconName : ""
        sourceSize.width: iconButton.size
        sourceSize.height: iconButton.size
        fillMode: Image.PreserveAspectFit
    }
    Glyph {
        visible: iconButton.label === "" && iconButton.iconName === ""
        anchors.centerIn: parent
        width: iconButton.size
        height: iconButton.size
        kind: iconButton.kind
        active: iconButton.active
        ink: iconButton.ink
    }
    Label {
        visible: iconButton.label !== ""
        anchors.centerIn: parent
        text: iconButton.label
        color: "#222222"
        font.pixelSize: 13
    }
    Rectangle {
        anchors.fill: parent
        radius: 16
        color: iconHover.containsMouse ? "#F2F2F4" : "transparent"
        z: -1
    }
    MouseArea {
        id: iconHover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: iconButton.clicked()
        ToolTip.visible: containsMouse && iconButton.tip !== ""
        ToolTip.text: iconButton.tip
        ToolTip.delay: 400
    }
}
