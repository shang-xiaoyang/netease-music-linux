import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: bar
    color: "#FFFFFF"
    implicitHeight: 64

    property bool playing: false
    property bool liked: false
    property string title: "未在播放"
    property string artist: "未知歌手"
    property string artists: ""
    property string quality: ""
    property string qualityMenu: ""
    property string mode: "列表循环"
    property string cover: ""
    property real volume: 0.8
    property int position: 0
    property int duration: 0
    signal togglePlay()
    signal previousTrack()
    signal nextTrack()
    signal seekTo(int ms)
    signal cycleMode()
    signal volumeTo(real value)
    signal openLyric()
    signal toggleDeskLyric()
    signal pickQuality(string level)
    signal showQueue()
    signal toggleLike()
    signal openComments()
    signal collect()
    signal openMore()
    signal openArtist()
    signal pickArtist(string artistId, string name)

    function modeKind() {
        if (bar.mode.indexOf("随机") >= 0)
            return "shuffle"
        if (bar.mode.indexOf("单曲") >= 0)
            return "single"
        if (bar.mode.indexOf("列表播放") >= 0)
            return "order"
        return "repeat"
    }

    Slider {
        id: progress
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: -7
        height: 16
        from: 0
        to: Math.max(1, bar.duration)
        value: bar.position
        onMoved: bar.seekTo(Math.round(value))
        hoverEnabled: true
        ToolTip.visible: hovered
        ToolTip.text: "点击或拖动进度条跳转"
        ToolTip.delay: 400

        background: Rectangle {
            x: progress.leftPadding
            y: progress.topPadding + progress.availableHeight / 2 - 1
            width: progress.availableWidth
            height: 2
            color: "#E6E6E8"
            Rectangle {
                width: progress.visualPosition * parent.width
                height: parent.height
                color: "#EC4141"
            }
        }
        handle: Rectangle {
            x: progress.leftPadding + progress.visualPosition * (progress.availableWidth - width)
            y: progress.topPadding + progress.availableHeight / 2 - height / 2
            width: progress.pressed || progress.hovered ? 8 : 0
            height: width
            radius: width / 2
            color: "#EC4141"
        }
    }

    Row {
        id: leftCluster
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Image {
            width: 46
            height: 46
            source: bar.cover ? Qt.resolvedUrl("file://" + bar.cover) : ""
            sourceSize: Qt.size(46, 46)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: bar.openLyric()
                ToolTip.visible: containsMouse
                ToolTip.text: "查看歌词"
                ToolTip.delay: 400
            }
            Rectangle {
                anchors.fill: parent
                radius: 4
                color: "#F3D6D6"
                visible: parent.status !== Image.Ready
                Label {
                    anchors.centerIn: parent
                    text: "♪"
                    color: "#EC4141"
                    font.pixelSize: 16
                }
            }
        }

        Column {
            width: 210
            spacing: 0
            anchors.verticalCenter: parent.verticalCenter
            Row {
                width: parent.width
                spacing: 6
                Label {
                    text: bar.title
                    color: "#222222"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, 108)
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bar.openLyric()
                        ToolTip.visible: containsMouse
                        ToolTip.text: "查看歌词"
                        ToolTip.delay: 400
                    }
                }
                Label {
                    text: bar.artist
                    color: "#507DAF"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    width: parent.width - x
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var people = (bar.artists || "").split("|").filter(function(item) { return item !== "" })
                            if (people.length < 2) {
                                bar.openArtist()
                                return
                            }
                            playArtistMenu.people = people
                            playArtistMenu.popup()
                        }
                        Menu {
                            id: playArtistMenu
                            property var people: []
                            Instantiator {
                                model: playArtistMenu.people
                                delegate: MenuItem {
                                    property string personId: modelData.split(",")[0]
                                    property string personName: modelData.split(",").slice(1).join(",")
                                    text: personName
                                    onTriggered: bar.pickArtist(personId, personName)
                                }
                                onObjectAdded: playArtistMenu.insertItem(index, object)
                                onObjectRemoved: playArtistMenu.removeItem(object)
                            }
                        }
                        ToolTip.visible: containsMouse
                        ToolTip.text: "打开歌手：" + bar.artist
                        ToolTip.delay: 400
                    }
                }
            }
            Row {
                spacing: 0
                IconButton { kind: "heart"; active: bar.liked; ink: bar.liked ? "#EC4141" : "#222222"; tip: bar.liked ? "取消喜欢" : "喜欢"; onClicked: bar.toggleLike() }
                IconButton { kind: "comment"; tip: "评论"; onClicked: bar.openComments() }
                IconButton { iconName: "list-add-symbolic"; tip: "收藏到歌单"; onClicked: bar.collect() }
            }
        }
    }

    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        IconButton { iconName: bar.modeKind() === "shuffle" ? "media-playlist-shuffle-symbolic" : bar.modeKind() === "single" ? "media-playlist-repeat-one-symbolic" : bar.modeKind() === "order" ? "media-playlist-consecutive-symbolic" : "media-playlist-repeat-symbolic"; tip: bar.mode; onClicked: bar.cycleMode() }
        IconButton { iconName: "media-skip-backward-symbolic"; tip: "上一首"; onClicked: bar.previousTrack() }
        IconButton { iconName: bar.playing ? "media-playback-pause-symbolic" : "media-playback-start-symbolic"; tip: bar.playing ? "暂停" : "播放"; size: 20; onClicked: bar.togglePlay() }
        IconButton { iconName: "media-skip-forward-symbolic"; tip: "下一首"; onClicked: bar.nextTrack() }
        IconButton { iconName: "view-list-symbolic"; tip: "播放列表"; onClicked: bar.showQueue() }
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 0
        Item {
            id: qualityButton
            width: Math.max(64, qualityLabel.implicitWidth + 16)
            height: 24
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                anchors.fill: parent
                radius: 12
                color: qualityMouse.containsMouse ? "#F3F3F5" : "#F7F7F8"
                border.color: "#E6E6E8"
                border.width: 1
            }
            Label {
                id: qualityLabel
                anchors.centerIn: parent
                text: bar.quality ? bar.quality.split(" ")[0] : "音质"
                color: "#333333"
                font.pixelSize: 11
            }
            MouseArea {
                id: qualityMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (bar.qualityMenu === "")
                        return
                    qualityPopup.open()
                }
                ToolTip.visible: containsMouse && !qualityPopup.visible
                ToolTip.text: "播放音质"
                ToolTip.delay: 400
            }
            Popup {
                id: qualityPopup
                y: -height - 6
                x: (parent.width - width) / 2
                width: 148
                height: bar.qualityMenu === "" ? 0 : bar.qualityMenu.split("\n").length * 26 + 8
                padding: 4
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                background: Rectangle {
                    color: "#FFFFFF"
                    radius: 8
                    border.color: "#E6E6E8"
                }
                contentItem: Column {
                    spacing: 0
                    Repeater {
                        model: bar.qualityMenu === "" ? [] : bar.qualityMenu.split("\n")
                        delegate: Item {
                            width: 140
                            height: 26
                            property string level: modelData.split("|")[0]
                            property string caption: (modelData.split("|")[1] || "").split(" ")[0]
                            Rectangle {
                                anchors.fill: parent
                                radius: 4
                                color: rowMouse.containsMouse ? "#FDECEC" : "transparent"
                            }
                            Label {
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                text: caption
                                color: caption === qualityLabel.text ? "#EC4141" : "#333333"
                                font.pixelSize: 12
                            }
                            MouseArea {
                                id: rowMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: {
                                    bar.pickQuality(level)
                                    qualityPopup.close()
                                }
                            }
                        }
                    }
                }
            }
        }
        IconButton { label: "词"; tip: "桌面歌词"; onClicked: bar.toggleDeskLyric() }
        IconButton { iconName: bar.volume <= 0.01 ? "audio-volume-muted-symbolic" : "audio-volume-high-symbolic"; tip: "系统音量"; onClicked: volumePopup.open() }
        IconButton { iconName: "view-more-symbolic"; tip: "更多"; onClicked: bar.openMore() }
    }

    Popup {
        id: volumePopup
        x: parent.width - width - 36
        y: -height - 6
        width: 36
        height: 120
        padding: 8
        Slider {
            anchors.fill: parent
            orientation: Qt.Vertical
            from: 0
            to: 1
            value: bar.volume
            onMoved: bar.volumeTo(value)
        }
    }

    component IconButton: Item {
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
}
