pragma Singleton
import QtQuick 2.12

QtObject {
    readonly property var palette: SystemPalette { colorGroup: SystemPalette.Active }
    readonly property color page: palette.window
    readonly property color sidebar: palette.base
    readonly property color card: palette.base
    readonly property color ink: palette.text
    readonly property color muted: palette.mid
    readonly property color line: palette.midlight
    readonly property color red: palette.highlight
    readonly property color onRed: palette.highlightedText
    readonly property color redHover: Qt.darker(palette.highlight, 1.08)
    readonly property color redSoft: Qt.rgba(palette.highlight.r, palette.highlight.g, palette.highlight.b, 0.14)
    readonly property color hover: palette.alternateBase
    readonly property int radius: 8
}
