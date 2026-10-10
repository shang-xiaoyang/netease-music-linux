import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtGraphicalEffects 1.15
import QtQml 2.15
import "components"

ApplicationWindow {
    id: window
    visible: true
    title: "网易云音乐（非官方）"
    color: "transparent"
    minimumWidth: 860
    minimumHeight: 560
    flags: Qt.Window | Qt.FramelessWindowHint

    Rectangle {
        id: frame
        anchors.fill: parent
        color: "#F5F5F7"
        radius: window.visibility === 4 ? 0 : 12
        border.color: window.visibility === 4 ? "transparent" : "#D8D8DC"
        border.width: 1
        z: -1
    }

    onClosing: {
        close.accepted = false
        hide()
        appBridge.hideToTray()
    }

    property bool searching: search.activeFocus
    property var searchItem: search
    property bool blurSearch: false
    onBlurSearchChanged: if (blurSearch) { blurSearch = false; leaveSearch() }
    property bool searchWanted: false
    property bool escapeWanted: false
    onSearchWantedChanged: if (searchWanted) { search.forceActiveFocus(); searchWanted = false }
    onEscapeWantedChanged: if (escapeWanted) { escapeWanted = false; handleEscape() }
    property string pageName: "home"
    property string pageTitle: "推荐"
    property int listReset: 0
    property bool playing: false
    property bool liked: false
    property string songTitle: "未在播放"
    property string songArtist: ""
    property string songAlbum: ""
    property string qualityText: ""
    property string coverPath: ""
    property real volume: 0.8
    property string modeText: "列表循环"
    property int position: 0
    property int duration: 0
    property var navModel: typeof navList !== "undefined" ? navList : null
    property var cardModel: typeof cardList !== "undefined" ? cardList : null
    property var songModel: typeof songList !== "undefined" ? songList : null
    property var albumModel: typeof albumList !== "undefined" ? albumList : null
    property var commentModel: typeof commentList !== "undefined" ? commentList : null
    property var downloadModel: typeof downloadList !== "undefined" ? downloadList : null
    property string loginKey: ""
    property string detailName: ""
    property string detailSub: ""
    property string detailBrief: ""
    property string detailCover: ""
    property string lyricText: "歌词加载中…"
    property string currentSongId: ""
    property string currentArtists: ""

    function clock(ms) {
        var value = Math.max(0, Math.floor(Number(ms || 0) / 1000))
        var min = Math.floor(value / 60)
        var sec = value % 60
        return (min < 10 ? "0" : "") + min + ":" + (sec < 10 ? "0" : "") + sec
    }

    Connections {
        target: appBridge
        function onStatusChanged(text) { status.text = text }
        function onStateChanged(state) { window.playing = state === "playing" }
        function onClockChanged(payload) {
            var parts = payload.split(",")
            window.position = Number(parts[0])
            window.duration = Number(parts[1])
        }
        function onSongChanged(payload) {
            var parts = payload.split("\n")
            window.songTitle = parts[1] || ""
            window.songArtist = parts[2] || ""
            window.songAlbum = parts[6] || ""
            window.duration = Number(parts[4] || 0)
            window.currentArtists = parts[5] || ""
            if (parts[0] !== window.currentSongId) {
                window.position = 0
                window.playing = true
            }
        }
        function onPageChanged(name, title) {
            window.pageName = name
            window.pageTitle = title
            if (name === "list")
                window.listReset = window.listReset + 1
        }
        function onAccountChanged(label) { account.text = label }
        function onModeChanged(label) { window.modeText = label }
        function onQualityChanged(label) { window.qualityText = label }
        function onVolumeChanged(value) { window.volume = value }
        function onCoverChanged(path) { window.coverPath = path }
        function onDetailChanged(payload) {
            if (payload.indexOf("cover\n") === 0) {
                window.detailCover = payload.slice(6)
                return
            }
            var parts = payload.split("\n")
            window.detailName = parts[0] || ""
            window.detailSub = parts[1] || ""
            window.detailBrief = parts.slice(2).join("\n")
            window.detailCover = ""
        }
        function onLyricChanged(text) { window.lyricText = text }
        function onLoginKeyChanged(key) { window.loginKey = key }
        function onQualitiesChanged(text) { qualityMenu.model = text }
        function onLikedChanged(value) { window.liked = value }
        function onCurrentSongChanged(songId) { window.currentSongId = songId }
    }

    Rectangle {
        id: titleBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 52
        color: "#FFFFFF"
        radius: window.visibility === 4 ? 0 : 12
        z: 2
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#E6E6E8"
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 8
            spacing: 12
            Rectangle {
                width: 22
                height: 22
                radius: 5
                color: "#EC4141"
                Label {
                    anchors.centerIn: parent
                    text: "♪"
                    color: "white"
                    font.pixelSize: 13
                }
            }
            Label {
                text: "网易云音乐（非官方）"
                color: "#333333"
                font.pixelSize: 14
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                id: searchBox
                parent: titleBar
                width: Math.min(360, Math.max(160, titleBar.width - 520))
                height: 32
                x: (titleBar.width - width) / 2
                y: (titleBar.height - height) / 2
                radius: 16
                color: "#F5F5F7"
                z: 2
                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    spacing: 6
                    Image {
                        width: 14
                        height: 14
                        source: "image://icon/edit-find-symbolic"
                        sourceSize: Qt.size(14, 14)
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    TextField {
                        id: search
                        width: parent.width - 28
                        height: 32
                        placeholderText: "搜索歌曲、歌手"
                        selectByMouse: true
                        background: Item {}
                        leftPadding: 0
                        rightPadding: 0
                        onAccepted: {
                            appBridge.search(text)
                            leaveSearch()
                        }
                        onActiveFocusChanged: if (!activeFocus) text = ""
                        Keys.onEscapePressed: handleEscape()
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                id: account
                text: "登录"
                flat: true
                z: 3
                onClicked: accountPopup.open()
            }
            Item {
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
                Rectangle { anchors.fill: parent; radius: 14; color: minHover.containsMouse ? "#F2F2F4" : "transparent"; z: -1 }
                Image { anchors.centerIn: parent; width: 16; height: 16; source: "image://icon/window-minimize-symbolic"; sourceSize: Qt.size(16, 16) }
                MouseArea {
                    id: minHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: window.showMinimized()
                    ToolTip.visible: containsMouse
                    ToolTip.text: "最小化"
                    ToolTip.delay: 400
                }
            }
            Item {
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
                Rectangle { anchors.fill: parent; radius: 14; color: maxHover.containsMouse ? "#F2F2F4" : "transparent"; z: -1 }
                Image { anchors.centerIn: parent; width: 16; height: 16; source: window.visibility === 4 ? "image://icon/window-restore-symbolic" : "image://icon/window-maximize-symbolic"; sourceSize: Qt.size(16, 16) }
                MouseArea {
                    id: maxHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: window.visibility === 4 ? window.showNormal() : window.showMaximized()
                    ToolTip.visible: containsMouse
                    ToolTip.text: window.visibility === 4 ? "还原" : "最大化"
                    ToolTip.delay: 400
                }
            }
            Item {
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
                Rectangle { anchors.fill: parent; radius: 14; color: closeHover.containsMouse ? "#F2F2F4" : "transparent"; z: -1 }
                Image { anchors.centerIn: parent; width: 16; height: 16; source: "image://icon/window-close-symbolic"; sourceSize: Qt.size(16, 16) }
                MouseArea {
                    id: closeHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: window.close()
                    ToolTip.visible: containsMouse
                    ToolTip.text: "关闭"
                    ToolTip.delay: 400
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            propagateComposedEvents: true
            onDoubleClicked: window.visibility === 4 ? window.showNormal() : window.showMaximized()
            onPressed: function(mouse) {
                var searchPoint = searchBox.mapFromItem(titleBar, mouse.x, mouse.y)
                var accountPoint = account.mapFromItem(titleBar, mouse.x, mouse.y)
                var onSearch = searchPoint.x >= 0 && searchPoint.x <= searchBox.width && searchPoint.y >= 0 && searchPoint.y <= searchBox.height
                var onAccount = accountPoint.x >= 0 && accountPoint.x <= account.width && accountPoint.y >= 0 && accountPoint.y <= account.height
                if (onSearch || onAccount)
                    mouse.accepted = false
                else {
                    leaveSearch()
                    window.startSystemMove()
                }
            }
        }
    }

    Item {
        anchors.top: titleBar.bottom
        anchors.bottom: playColumn.top
        anchors.left: parent.left
        anchors.right: parent.right

        Rectangle {
            id: sideBar
            width: 196
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            color: "#FFFFFF"
            ListView {
                id: nav
                anchors.fill: parent
                anchors.topMargin: 8
                model: window.navModel
                clip: true
                delegate: Item {
                    width: nav.width
                    height: kind === "section" ? 28 : 34
                    Rectangle {
                        anchors.fill: parent
                        color: kind === "section" ? "transparent" : (mouse.hovered ? "#E8F3FF" : (window.pageTitle === label ? "#FDECEC" : "transparent"))
                    }
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 8
                        spacing: 8
                        visible: kind !== "section"
                        Rectangle {
                            width: 16
                            height: 16
                            radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: "#F3D6D6"
                            visible: kind === "playlist" || kind === "chart" || kind === "liked"
                            Image {
                                anchors.fill: parent
                                source: local ? Qt.resolvedUrl("file://" + local) : ""
                                sourceSize: Qt.size(16, 16)
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                            Label {
                                anchors.centerIn: parent
                                text: kind === "liked" ? "♥" : "♪"
                                color: "#EC4141"
                                font.pixelSize: 9
                                visible: parent.status !== Image.Ready && !local
                            }
                        }
                        Label {
                            text: label
                            width: parent.width - (kind === "playlist" || kind === "chart" || kind === "liked" ? 24 : 0)
                            color: window.pageTitle === label ? "#EC4141" : "#333333"
                            font.pixelSize: 13
                            elide: Text.ElideRight
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Label {
                        anchors.fill: parent
                        visible: kind === "section"
                        text: label
                        color: "#8E8E93"
                        font.pixelSize: 11
                        leftPadding: 16
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    MouseArea {
                        id: mouse
                        anchors.fill: parent
                        enabled: kind !== "section"
                        hoverEnabled: true
                        onClicked: appBridge.openNav(key)
                    }
                }
            }
        }

        Item {
            id: lyricStage
            anchors.fill: parent
            visible: window.pageName === "lyric"
            z: 3
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#FFF6F6" }
                    GradientStop { position: 1.0; color: "#F4F4F7" }
                }
            }
            Rectangle {
                width: 32
                height: 32
                radius: 16
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 12
                color: lyricBack.containsMouse ? "#FDECEC" : "#FFFFFF"
                border.color: "#E6E6EA"
                Label {
                    anchors.centerIn: parent
                    text: "‹"
                    color: "#333333"
                    font.pixelSize: 18
                }
                MouseArea {
                    id: lyricBack
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: appBridge.goBack()
                    ToolTip.visible: containsMouse
                    ToolTip.text: "返回"
                    ToolTip.delay: 400
                }
            }
            Item {
                id: vinyl
                width: Math.min(232, parent.width * 0.28)
                height: width
                anchors.left: parent.left
                anchors.leftMargin: Math.max(48, (parent.width * 0.36 - width) / 2)
                anchors.verticalCenter: parent.verticalCenter
                Item {
                    id: disc
                    anchors.fill: parent
                    Rectangle {
                        anchors.fill: parent
                        radius: width / 2
                        color: "#2A2A2E"
                    }
                    Repeater {
                        model: 6
                        Rectangle {
                            anchors.centerIn: parent
                            width: disc.width * (0.90 - index * 0.06)
                            height: width
                            radius: width / 2
                            color: "transparent"
                            border.color: index % 2 ? "#3A3A40" : "#242428"
                            border.width: 1
                        }
                    }
                    Item {
                        id: coverHole
                        anchors.centerIn: parent
                        width: parent.width * 0.58
                        height: width
                        Image {
                            id: coverImage
                            anchors.fill: parent
                            source: window.coverPath ? Qt.resolvedUrl("file://" + window.coverPath) : ""
                            sourceSize: Qt.size(200, 200)
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            visible: false
                        }
                        Rectangle {
                            id: coverMask
                            anchors.fill: parent
                            radius: width / 2
                            visible: false
                        }
                        OpacityMask {
                            anchors.fill: parent
                            source: coverImage
                            maskSource: coverMask
                        }
                        Rectangle {
                            anchors.fill: parent
                            radius: width / 2
                            color: "#F2F2F4"
                            visible: coverImage.status !== Image.Ready
                            Label {
                                anchors.centerIn: parent
                                text: "♪"
                                color: "#EC4141"
                                font.pixelSize: 22
                            }
                        }
                    }
                    Rectangle {
                        anchors.centerIn: parent
                        width: 12
                        height: 12
                        radius: 6
                        color: "#F7F7F8"
                        border.color: "#C8C8CC"
                        border.width: 2
                        z: 1
                    }
                }
                RotationAnimation {
                    id: vinylSpin
                    target: disc
                    property: "rotation"
                    from: disc.rotation
                    to: disc.rotation + 360
                    duration: 18000
                    loops: Animation.Infinite
                    running: window.playing && lyricStage.visible
                }
                Item {
                    id: tonearm
                    width: vinyl.width * 0.46
                    height: 16
                    x: vinyl.width * 0.50
                    y: vinyl.width * 0.08
                    transformOrigin: Item.Left
                    rotation: window.playing ? 28 : -6
                    Behavior on rotation { NumberAnimation { duration: 450 } }
                    Rectangle {
                        width: 7
                        height: 7
                        radius: 4
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        color: "#C8C8CC"
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 5
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 8
                        height: 3
                        radius: 1
                        color: "#D0D0D4"
                    }
                    Rectangle {
                        width: 8
                        height: 8
                        radius: 2
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        color: "#EC4141"
                    }
                }
            }
            Item {
                anchors.left: vinyl.right
                anchors.leftMargin: 72
                anchors.right: parent.right
                anchors.rightMargin: 48
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.topMargin: 28
                anchors.bottomMargin: 16
                Label {
                    id: lyricTitle
                    width: parent.width
                    text: window.songTitle || "未在播放"
                    color: "#222222"
                    font.pixelSize: 26
                    font.bold: true
                    elide: Text.ElideRight
                }
                Label {
                    id: lyricMeta
                    anchors.top: lyricTitle.bottom
                    anchors.topMargin: 8
                    width: parent.width
                    text: (window.songAlbum ? "专辑：" + window.songAlbum + "    " : "") + (window.songArtist ? "歌手：" + window.songArtist : "")
                    color: "#8A8A90"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
                ListView {
                    id: lyricView
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: lyricMeta.bottom
                    anchors.bottom: parent.bottom
                    anchors.topMargin: 22
                    clip: true
                    model: window.lyricText === "" ? ["0\t歌词加载中…"] : window.lyricText.split("\n")
                    property int lineAt: {
                        var lines = model
                        var at = 0
                        for (var i = 0; i < lines.length; i++) {
                            var ms = Number(String(lines[i]).split("\t")[0])
                            if (!isNaN(ms) && ms <= window.position)
                                at = i
                        }
                        return at
                    }
                    currentIndex: lineAt
                    preferredHighlightBegin: height * 0.28
                    preferredHighlightEnd: height * 0.28 + 28
                    highlightRangeMode: ListView.StrictlyEnforceRange
                    delegate: Label {
                        width: lyricView.width
                        height: implicitHeight + 16
                        text: String(modelData).split("\t").slice(1).join("\t")
                        color: index === lyricView.currentIndex ? "#EC4141" : (Math.abs(index - lyricView.currentIndex) <= 2 ? "#5C5C62" : "#B0B0B6")
                        font.pixelSize: index === lyricView.currentIndex ? 18 : 15
                        font.bold: index === lyricView.currentIndex
                        wrapMode: Text.Wrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        Rectangle {
            anchors.left: sideBar.right
            width: 1
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            color: "#E6E6E8"
        }

        Item {
            anchors.left: sideBar.right
            anchors.leftMargin: 1
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            Row {
                id: pageHead
                visible: window.pageName !== "home"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 8
                anchors.topMargin: 8
                height: visible ? 36 : 0
                spacing: 4
                Item {
                    width: 28
                    height: 28
                    anchors.verticalCenter: parent.verticalCenter
                    Label {
                        anchors.centerIn: parent
                        text: "‹"
                        color: "#333333"
                        font.pixelSize: 18
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: appBridge.goBack()
                        ToolTip.visible: containsMouse
                        ToolTip.text: "返回"
                        ToolTip.delay: 400
                    }
                }
                Label {
                    text: window.pageTitle
                    color: "#333333"
                    font.pixelSize: 18
                    font.bold: true
                    elide: Text.ElideRight
                    width: parent.width - 48
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            StackLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: pageHead.bottom
                anchors.bottom: parent.bottom
                currentIndex: window.pageName === "discover" ? 1 : window.pageName === "list" ? 2 : window.pageName === "album" ? 3 : window.pageName === "artist" ? 4 : window.pageName === "lyric" ? 5 : window.pageName === "comments" ? 6 : window.pageName === "user" ? 7 : window.pageName === "downloads" ? 8 : 0

                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: width
                    contentHeight: homeColumn.implicitHeight + 24
                    clip: true
                    visible: window.pageName === "home"
                    Column {
                        id: homeColumn
                        width: parent.width
                        spacing: 12
                        topPadding: 8
                        Label {
                            text: "推荐"
                            color: "#222222"
                            font.pixelSize: 18
                            font.bold: true
                            leftPadding: 22
                        }
                        Row {
                            spacing: 12
                            leftPadding: 22
                            Repeater {
                                model: cardList
                                delegate: Item {
                                    width: kind === "chart" ? 148 : 0
                                    height: kind === "chart" ? 78 : 0
                                    visible: kind === "chart"
                                    Rectangle {
                                        width: 148
                                        height: 78
                                        radius: 8
                                        color: "#F3D6D6"
                                        clip: true
                                        Image {
                                            anchors.fill: parent
                                            source: local ? Qt.resolvedUrl("file://" + local) : ""
                                            sourceSize: Qt.size(148, 78)
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: appBridge.openPlaylist(itemId, name)
                                    }
                                }
                            }
                        }
                        Label {
                            text: "推荐歌单"
                            color: "#222222"
                            font.pixelSize: 18
                            font.bold: true
                            leftPadding: 22
                            topPadding: 8
                        }
                        Flow {
                            width: Math.min(parent.width - 44, 6 * 132 - 12)
                            x: 22
                            spacing: 12
                            Repeater {
                                model: cardList
                                delegate: Item {
                                    width: kind === "playlist" ? 120 : 0
                                    height: kind === "playlist" ? 164 : 0
                                    visible: kind === "playlist"
                                    Column {
                                        spacing: 4
                                        Rectangle {
                                            width: 120
                                            height: 120
                                            radius: 8
                                            color: "#F3D6D6"
                                            clip: true
                                            Image {
                                                anchors.fill: parent
                                                source: local ? Qt.resolvedUrl("file://" + local) : ""
                                                sourceSize: Qt.size(120, 120)
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                            }
                                        }
                                        Label { text: name; width: 120; elide: Text.ElideRight; color: "#222222"; font.pixelSize: 12 }
                                        Label { text: count + " 首"; color: "#8E8E93"; font.pixelSize: 11 }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: appBridge.openPlaylist(itemId, name)
                                    }
                                }
                            }
                        }
                    }
                }

                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: width
                    contentHeight: discoverFlow.implicitHeight + 24
                    clip: true
                    visible: window.pageName === "discover"
                    Flow {
                        id: discoverFlow
                        width: Math.min(parent.width - 44, 6 * 132 - 12)
                        x: 22
                        y: 12
                        spacing: 12
                        Repeater {
                            model: cardList
                            delegate: Item {
                                width: kind === "playlist" ? 120 : 0
                                height: kind === "playlist" ? 164 : 0
                                visible: kind === "playlist"
                                Column {
                                    spacing: 4
                                    Rectangle {
                                        width: 120
                                        height: 120
                                        radius: 8
                                        color: "#F3D6D6"
                                        clip: true
                                        Image {
                                            anchors.fill: parent
                                            source: local ? Qt.resolvedUrl("file://" + local) : ""
                                            sourceSize: Qt.size(120, 120)
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                        }
                                    }
                                    Label { text: name; width: 120; elide: Text.ElideRight; color: "#222222"; font.pixelSize: 12 }
                                    Label { text: count + " 首"; color: "#8E8E93"; font.pixelSize: 11 }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: appBridge.openPlaylist(itemId, name)
                                }
                            }
                        }
                    }
                }

                Loader {
                    active: window.pageName === "list"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: songPage
                }
                Component {
                    id: songPage
                ListView {
                    id: songView
                    objectName: "songView"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: window.songModel
                    cacheBuffer: 240
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    onAtYEndChanged: if (atYEnd && count > 0) appBridge.moreSongs()
                    Connections {
                        target: window
                        function onListResetChanged() { songView.positionViewAtBeginning() }
                    }
                    delegate: ItemDelegate {
                        width: songView.width
                        height: 56
                        onDoubleClicked: appBridge.playRow(index)
                        onPressAndHold: songMenu.popup()
                        background: Rectangle {
                            color: model.songId === window.currentSongId ? "#FDECEC" : (parent.hovered ? "#E8F3FF" : "transparent")
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.RightButton
                            onClicked: songMenu.popup()
                        }
                        Menu {
                            id: songMenu
                            MenuItem { text: "⏭  下一首播放"; onTriggered: appBridge.playNext(index) }
                            MenuItem {
                                text: (appBridge.songLiked(model.songId) ? "♥  取消喜欢" : "♡  加入喜欢")
                                onTriggered: appBridge.toggleLike(index)
                            }
                            MenuItem { text: "↓  下载"; onTriggered: appBridge.enqueueDownload(index) }
                            MenuItem { text: "✎  查看评论"; onTriggered: appBridge.openComments(index) }
                            MenuItem {
                                text: "✕  从当前歌单移除"
                                visible: appBridge.canRemoveCurrent()
                                height: visible ? implicitHeight : 0
                                onTriggered: appBridge.removeFromPlaylist(index)
                            }
                            Menu {
                                id: collectMenu
                                title: "收藏到歌单"
                                Instantiator {
                                    model: !appBridge || appBridge.createdPlaylists() === "" ? [] : appBridge.createdPlaylists().split("\n")
                                    delegate: MenuItem {
                                        text: modelData.split("|")[1]
                                        onTriggered: appBridge.collectTo(index, modelData.split("|")[0])
                                    }
                                    onObjectAdded: collectMenu.insertItem(index, object)
                                    onObjectRemoved: collectMenu.removeItem(object)
                                }
                            }
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 16
                            anchors.rightMargin: 16
                            spacing: 10
                            Label { text: index + 1; color: "#8E8E93"; Layout.preferredWidth: 28 }
                            Rectangle {
                                width: 36
                                height: 36
                                radius: 8
                                color: "#F3D6D6"
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    source: model.local ? Qt.resolvedUrl("file://" + model.local) : ""
                                    sourceSize: Qt.size(36, 36)
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                }
                            }
                            Label {
                                text: model.name || ""
                                color: model.songId === window.currentSongId ? "#EC4141" : "#333333"
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                            Label { text: model.vip ? "VIP" : ""; color: "#EC4141"; font.pixelSize: 11 }
                            Label {
                                text: model.artist || ""
                                color: "#507DAF"
                                Layout.preferredWidth: 140
                                elide: Text.ElideRight
                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        var people = (model.artists || "").split("|").filter(function(item) { return item !== "" })
                                        if (people.length < 2) {
                                            appBridge.openArtist(model.artistId, model.artist)
                                            return
                                        }
                                        artistMenu.people = people
                                        artistMenu.popup()
                                    }
                                    Menu {
                                        id: artistMenu
                                        property var people: []
                                        Instantiator {
                                            model: artistMenu.people
                                            delegate: MenuItem {
                                                property string personId: modelData.split(",")[0]
                                                property string personName: modelData.split(",").slice(1).join(",")
                                                text: personName
                                                onTriggered: appBridge.openArtist(personId, personName)
                                            }
                                            onObjectAdded: artistMenu.insertItem(index, object)
                                            onObjectRemoved: artistMenu.removeItem(object)
                                        }
                                    }
                                    ToolTip.visible: containsMouse
                                    ToolTip.text: "打开歌手：" + (model.artist || "")
                                    ToolTip.delay: 300
                                }
                            }
                            Label {
                                text: model.album || ""
                                color: "#507DAF"
                                Layout.preferredWidth: 140
                                elide: Text.ElideRight
                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: appBridge.openAlbum(model.albumId, model.album)
                                    ToolTip.visible: containsMouse
                                    ToolTip.text: "打开专辑：" + (model.album || "")
                                    ToolTip.delay: 300
                                }
                            }
                            Label {
                                text: clock(model.duration)
                                color: "#8E8E93"
                                Layout.preferredWidth: 48
                            }
                        }
                    }
                }
                }

                Loader {
                    active: window.pageName === "album"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: albumPage
                }
                Component {
                    id: albumPage
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 12
                    Row {
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.topMargin: 8
                        Layout.preferredHeight: 168
                        Layout.fillWidth: true
                        spacing: 18
                        Rectangle {
                            width: 168
                            height: 168
                            radius: 8
                            color: "#F3D6D6"
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: window.detailCover ? Qt.resolvedUrl("file://" + window.detailCover) : ""
                                sourceSize: Qt.size(132, 132)
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                        }
                        Column {
                            width: parent.width - 186
                            spacing: 6
                            anchors.verticalCenter: parent.verticalCenter
                            Label {
                                text: window.detailName
                                color: "#222222"
                                font.pixelSize: 20
                                font.bold: true
                                width: parent.width
                                wrapMode: Text.Wrap
                            }
                            Label {
                                text: window.detailSub
                                color: "#507DAF"
                                font.pixelSize: 13
                                visible: text !== ""
                            }
                            Label {
                                text: window.detailBrief
                                color: "#666666"
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                width: parent.width
                                maximumLineCount: 4
                                elide: Text.ElideRight
                                visible: text !== ""
                            }
                        }
                    }
                    ListView {
                        id: detailSongs
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: window.songModel
                        clip: true
                        delegate: ItemDelegate {
                            width: detailSongs.width
                            height: 48
                            onDoubleClicked: appBridge.playRow(index)
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                spacing: 10
                                Label { text: index + 1; color: "#8E8E93"; Layout.preferredWidth: 28 }
                                Rectangle {
                                    width: 36
                                    height: 36
                                    radius: 4
                                    color: "#F3D6D6"
                                    clip: true
                                    Image {
                                        anchors.fill: parent
                                        source: model.local ? Qt.resolvedUrl("file://" + model.local) : ""
                                        sourceSize: Qt.size(36, 36)
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                    }
                                }
                                Label { text: model.name || ""; Layout.fillWidth: true; elide: Text.ElideRight; color: "#333333" }
                                Label { text: model.artist || ""; color: "#8E8E93"; Layout.preferredWidth: 140; elide: Text.ElideRight }
                                Label { text: clock(model.duration); color: "#8E8E93"; Layout.preferredWidth: 48 }
                            }
                        }
                    }
                }
                }

                Loader {
                    active: window.pageName === "artist"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: artistPage
                }
                Component {
                    id: artistPage
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 12
                    Row {
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.topMargin: 8
                        Layout.preferredHeight: 132
                        Layout.fillWidth: true
                        spacing: 18
                        Rectangle {
                            width: 132
                            height: 132
                            radius: 66
                            color: "#F3D6D6"
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: window.detailCover ? Qt.resolvedUrl("file://" + window.detailCover) : ""
                                sourceSize: Qt.size(132, 132)
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                        }
                        Column {
                            width: parent.width - 150
                            spacing: 6
                            anchors.verticalCenter: parent.verticalCenter
                            Label {
                                text: window.detailName
                                color: "#222222"
                                font.pixelSize: 20
                                font.bold: true
                                width: parent.width
                                elide: Text.ElideRight
                            }
                            Label {
                                text: window.detailSub
                                color: "#8E8E93"
                                font.pixelSize: 12
                                visible: text !== ""
                                width: parent.width
                                elide: Text.ElideRight
                            }
                            Label {
                                text: window.detailBrief
                                color: "#666666"
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                width: parent.width
                                maximumLineCount: 4
                                elide: Text.ElideRight
                                visible: text !== ""
                            }
                        }
                    }
                    Label {
                        text: "专辑"
                        color: "#333333"
                        font.pixelSize: 14
                        font.bold: true
                        Layout.leftMargin: 16
                        visible: albumChips.count > 0
                    }
                    ListView {
                        id: albumChips
                        Layout.fillWidth: true
                        Layout.preferredHeight: albumChips.count > 0 ? 148 : 0
                        Layout.leftMargin: 16
                        orientation: ListView.Horizontal
                        spacing: 12
                        model: window.albumModel
                        clip: true
                        delegate: Item {
                            width: 96
                            height: 140
                            Column {
                                spacing: 4
                                Rectangle {
                                    width: 96
                                    height: 96
                                    radius: 6
                                    color: "#F3D6D6"
                                    clip: true
                                    Image {
                                        anchors.fill: parent
                                        source: model.local ? Qt.resolvedUrl("file://" + model.local) : ""
                                        sourceSize: Qt.size(36, 36)
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                    }
                                }
                                Label {
                                    text: model.name || ""
                                    width: 96
                                    color: "#333333"
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                                Label {
                                    text: model.publish || ""
                                    width: 96
                                    color: "#8E8E93"
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: appBridge.openAlbum(model.itemId, model.name)
                            }
                        }
                    }
                    ListView {
                        id: artistSongs
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: window.songModel
                        clip: true
                        delegate: ItemDelegate {
                            width: artistSongs.width
                            height: 48
                            onDoubleClicked: appBridge.playRow(index)
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                spacing: 10
                                Label { text: index + 1; color: "#8E8E93"; Layout.preferredWidth: 28 }
                                Rectangle {
                                    width: 36
                                    height: 36
                                    radius: 4
                                    color: "#F3D6D6"
                                    clip: true
                                    Image {
                                        anchors.fill: parent
                                        source: model.local ? Qt.resolvedUrl("file://" + model.local) : ""
                                        sourceSize: Qt.size(36, 36)
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                    }
                                }
                                Label { text: model.name || ""; Layout.fillWidth: true; elide: Text.ElideRight; color: "#333333" }
                                Label { text: clock(model.duration); color: "#8E8E93"; Layout.preferredWidth: 48 }
                            }
                        }
                    }
                }
                }

                Item { Layout.fillWidth: true; Layout.fillHeight: true }

                Loader {
                    active: window.pageName === "comments"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: commentPage
                }
                Component {
                    id: commentPage
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0
                    Row {
                        Layout.leftMargin: 16
                        Layout.topMargin: 4
                        Layout.preferredHeight: 28
                        spacing: 16
                        Label {
                            text: "精彩评论"
                            color: commentTab.hot ? "#EC4141" : "#8E8E93"
                            font.pixelSize: 13
                            MouseArea {
                                id: commentTab
                                property bool hot: true
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { hot = true; appBridge.setCommentTab("hot") }
                            }
                        }
                        Label {
                            text: "最新评论"
                            color: !commentTab.hot ? "#EC4141" : "#8E8E93"
                            font.pixelSize: 13
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { commentTab.hot = false; appBridge.setCommentTab("latest") }
                            }
                        }
                    }
                    ListView {
                        id: commentView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: window.commentModel
                        clip: true
                        delegate: Item {
                            width: commentView.width
                            height: commentRow.implicitHeight + 20
                            Row {
                                id: commentRow
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                anchors.top: parent.top
                                anchors.topMargin: 10
                                spacing: 10
                                Rectangle {
                                    width: 36
                                    height: 36
                                    radius: 18
                                    color: "#F3D6D6"
                                    clip: true
                                    Image {
                                        anchors.fill: parent
                                        source: model.local ? Qt.resolvedUrl("file://" + model.local) : ""
                                        sourceSize: Qt.size(36, 36)
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                    }
                                }
                                Column {
                                    id: commentColumn
                                    width: parent.width - 46
                                    spacing: 4
                                    Label {
                                        text: model.nickname || "用户"
                                        color: "#507DAF"
                                        font.pixelSize: 13
                                        MouseArea {
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: appBridge.openUser(model.userId, model.nickname)
                                            ToolTip.visible: containsMouse
                                            ToolTip.text: "打开主页：" + (model.nickname || "")
                                            ToolTip.delay: 300
                                        }
                                    }
                                    Label { text: model.when || ""; color: "#8E8E93"; font.pixelSize: 11 }
                                    Label { id: body; text: model.content || ""; color: "#333333"; wrapMode: Text.Wrap; width: parent.width }
                                    Label { text: "♡ " + (model.liked || "0"); color: "#8E8E93"; font.pixelSize: 12 }
                                }
                            }
                        }
                        footer: Button {
                            text: "更多评论"
                            flat: true
                            visible: commentView.count > 0 && !commentTab.hot
                            onClicked: appBridge.moreComments()
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 48
                        color: "#FFFFFF"
                        border.color: "#E6E6E8"
                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 8
                            spacing: 8
                            TextField {
                                id: commentInput
                                width: parent.width - 72
                                placeholderText: "写评论，最多 140 字"
                                selectByMouse: true
                                maximumLength: 140
                                onAccepted: {
                                    appBridge.sendComment(text)
                                    text = ""
                                }
                            }
                            Button {
                                text: "发送"
                                flat: true
                                onClicked: {
                                    appBridge.sendComment(commentInput.text)
                                    commentInput.text = ""
                                }
                            }
                        }
                    }
                }
                }

                Loader {
                    active: window.pageName === "user"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: userPage
                }
                Component {
                    id: userPage
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Row {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.leftMargin: 16
                        anchors.topMargin: 16
                        anchors.right: parent.right
                        anchors.rightMargin: 16
                        spacing: 18
                        Rectangle {
                            width: 96
                            height: 96
                            radius: 48
                            color: "#F3D6D6"
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: window.detailCover ? Qt.resolvedUrl("file://" + window.detailCover) : ""
                                sourceSize: Qt.size(132, 132)
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                        }
                        Column {
                            width: parent.width - 114
                            spacing: 6
                            anchors.verticalCenter: parent.verticalCenter
                            Label {
                                text: window.detailName
                                color: "#222222"
                                font.pixelSize: 20
                                font.bold: true
                                width: parent.width
                                elide: Text.ElideRight
                            }
                            Label {
                                text: window.detailSub
                                color: "#8E8E93"
                                font.pixelSize: 13
                                visible: text !== ""
                            }
                            Label {
                                text: window.detailBrief
                                color: "#666666"
                                font.pixelSize: 13
                                wrapMode: Text.Wrap
                                width: parent.width
                            }
                            Button {
                                visible: window.pageTitle === "会员信息"
                                text: "打开官方开通页"
                                flat: true
                                onClicked: Qt.openUrlExternally("https://music.163.com/v/w/vip")
                            }
                        }
                    }
                }
                }

                ListView {
                    id: downloadView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: window.downloadModel
                    clip: true
                    delegate: Item {
                        width: downloadView.width
                        height: 36
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 16
                            anchors.rightMargin: 16
                            Label { text: name; Layout.fillWidth: true; elide: Text.ElideRight; color: "#333333" }
                            Label { text: status; color: "#8E8E93"; Layout.preferredWidth: 80 }
                            Label { text: quality; color: "#8E8E93"; Layout.preferredWidth: 110; elide: Text.ElideRight }
                        }
                    }
                }
            }

            Popup {
                id: loginPopup
                modal: true
                focus: true
                x: (parent.width - width) / 2
                y: 40
                width: 240
                height: 250
                visible: window.loginKey !== ""
                onClosed: appBridge.cancelLogin()
                Column {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 8
                    Label { text: "用网易云音乐 App 扫码"; color: "#333333" }
                    Image {
                        width: 180
                        height: 180
                        source: window.loginKey ? Qt.resolvedUrl("file://" + appBridge.loginQrPath(window.loginKey)) : ""
                        sourceSize: Qt.size(180, 180)
                        asynchronous: true
                    }
                }
            }
        }
    }

    Column {
        id: playColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        spacing: 0
        z: 2
        PlayBar {
            id: playBar
            width: parent.width
            playing: window.playing
            liked: window.liked
            title: window.songTitle
            artist: window.songArtist || "未知歌手"
            artists: window.currentArtists
            quality: window.qualityText
            qualityMenu: qualityMenu.model || ""
            mode: window.modeText
            cover: window.coverPath
            volume: window.volume
            position: window.position
            duration: window.duration
            onTogglePlay: appBridge.toggle()
            onPreviousTrack: appBridge.previous()
            onNextTrack: appBridge.next()
            onSeekTo: appBridge.seek(ms)
            onCycleMode: appBridge.cycleMode()
            onVolumeTo: appBridge.setVolume(value)
            onOpenLyric: appBridge.openLyric()
            onToggleDeskLyric: appBridge.toggleDeskLyric()
            onPickQuality: appBridge.setQuality(level)
            onShowQueue: queuePopup.visible ? queuePopup.close() : queuePopup.open()
            onToggleLike: appBridge.toggleLike(-1)
            onOpenComments: appBridge.openComments(-1)
            onCollect: {
                appBridge.openCollect()
                collectPopup.open()
            }
            onOpenMore: moreMenu.popup()
            onOpenArtist: appBridge.openCurrentArtist()
            onPickArtist: appBridge.openArtist(artistId, name)
        }
        Rectangle {
            width: parent.width
            height: 22
            color: "#F0F0F2"
            radius: window.visibility === 4 ? 0 : 12
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: "#E6E6E8"
            }
            Label {
                id: status
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                text: ""
                color: "#8E8E93"
                font.pixelSize: 11
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }
    }

    Item {
        id: keySink
        focus: true
    }

    function leaveSearch() {
        search.deselect()
        search.focus = false
        keySink.forceActiveFocus()
    }

    function handleEscape() {
        if (search.activeFocus || search.text !== "") {
            search.text = ""
            leaveSearch()
            return
        }
        if (queuePopup.visible)
            queuePopup.close()
        else if (window.pageName === "lyric" || window.pageName === "comments" || window.pageName === "downloads" || window.pageName === "user")
            appBridge.goBack()
    }

    Popup {
        id: accountPopup
        parent: window.contentItem
        modal: false
        width: 168
        height: account.text === "登录" ? 44 : 116
        x: Math.max(8, account.x + account.width - width)
        y: titleBar.height + 4
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: "#FFFFFF"; radius: 8; border.color: "#E6E6E8" }
        Column {
            anchors.fill: parent
            spacing: 0
            Item {
                width: parent.width
                height: 36
                visible: account.text === "登录"
                Label { anchors.centerIn: parent; text: "扫码登录"; color: "#333333"; font.pixelSize: 13 }
                MouseArea { anchors.fill: parent; onClicked: { accountPopup.close(); appBridge.startLogin() } }
            }
            Item {
                width: parent.width
                height: 36
                visible: account.text !== "登录"
                Label { anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.leftMargin: 12; text: "会员信息"; color: "#333333"; font.pixelSize: 13 }
                MouseArea { anchors.fill: parent; onClicked: { accountPopup.close(); appBridge.openVip() } }
            }
            Item {
                width: parent.width
                height: 36
                visible: account.text !== "登录"
                Label { anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.leftMargin: 12; text: "开通会员"; color: "#333333"; font.pixelSize: 13 }
                MouseArea { anchors.fill: parent; onClicked: { accountPopup.close(); Qt.openUrlExternally("https://music.163.com/v/w/vip") } }
            }
            Item {
                width: parent.width
                height: 36
                visible: account.text !== "登录"
                Label { anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.leftMargin: 12; text: "退出登录"; color: "#EC4141"; font.pixelSize: 13 }
                MouseArea { anchors.fill: parent; onClicked: { accountPopup.close(); appBridge.logout() } }
            }
        }
    }

    Popup {
        id: queuePopup
        parent: window.contentItem
        modal: false
        width: 320
        height: 360
        x: parent.width - width - 12
        y: playColumn.y - height - 8
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: "#FFFFFF"
            radius: 8
            border.color: "#E6E6E8"
        }
        ListView {
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            model: queueList
            header: Label {
                text: "当前播放 · " + window.modeText
                leftPadding: 12
                topPadding: 8
                bottomPadding: 6
                width: 312
                font.pixelSize: 13
                color: "#333333"
                elide: Text.ElideRight
            }
            delegate: Item {
                width: 312
                height: 32
                Rectangle {
                    anchors.fill: parent
                    color: model.songId === window.currentSongId ? "#FDECEC" : (hover.containsMouse ? "#F6F6F8" : "transparent")
                }
                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 8
                    Label {
                        text: (index + 1 < 10 ? "0" : "") + (index + 1)
                        width: 28
                        color: "#8E8E93"
                        font.pixelSize: 12
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Label {
                        text: model.name || ""
                        width: 150
                        color: model.songId === window.currentSongId ? "#EC4141" : "#333333"
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Label {
                        text: model.artist || ""
                        width: 100
                        color: "#8E8E93"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: {
                        if (mouse.button !== Qt.RightButton) {
                            appBridge.playQueue(index)
                            return
                        }
                        appBridge.openCollect()
                        queueMenu.popup()
                    }
                    onPressAndHold: {
                        appBridge.openCollect()
                        queueMenu.popup()
                    }
                }
                Menu {
                    id: queueMenu
                    MenuItem { text: "⏭  下一首播放"; onTriggered: appBridge.playNextQueue(index) }
                    MenuItem {
                        text: (appBridge.songLiked(model.songId) ? "♥  取消喜欢" : "♡  加入喜欢")
                        onTriggered: appBridge.toggleQueueLike(index)
                    }
                    Menu {
                        id: queueCollect
                        title: "收藏到歌单"
                        Instantiator {
                            model: collectList
                            delegate: MenuItem {
                                text: name
                                visible: kind !== "create"
                                height: visible ? implicitHeight : 0
                                onTriggered: appBridge.collectQueue(index, itemId)
                            }
                            onObjectAdded: queueCollect.insertItem(index, object)
                            onObjectRemoved: queueCollect.removeItem(object)
                        }
                    }
                    MenuItem { text: "✕  从播放列表移除"; onTriggered: appBridge.removeFromQueue(index) }
                }
            }
        }
    }

    Popup {
        id: collectPopup
        modal: true
        width: 360
        height: 420
        x: Math.max(8, (parent.width - width) / 2)
        y: Math.max(8, parent.height - height - 72)
        padding: 16
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        Column {
            anchors.fill: parent
            spacing: 8
            Label {
                text: "收藏到歌单"
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                color: "#222222"
                font.pixelSize: 15
            }
            Row {
                spacing: 16
                Label { text: "默认排序"; color: "#EC4141"; font.pixelSize: 13 }
                Label { text: "常用优先"; color: "#8E8E93"; font.pixelSize: 13 }
            }
            ListView {
                width: parent.width
                height: parent.height - 56
                clip: true
                model: collectList
                delegate: Item {
                    width: 328
                    height: 52
                    Row {
                        anchors.fill: parent
                        spacing: 12
                        Rectangle {
                            width: 40
                            height: 40
                            radius: 4
                            color: "#F3D6D6"
                            anchors.verticalCenter: parent.verticalCenter
                            Label {
                                anchors.centerIn: parent
                                text: kind === "create" ? "+" : "♪"
                                color: "#EC4141"
                                font.pixelSize: 16
                                visible: !local
                            }
                            Image {
                                anchors.fill: parent
                                source: local ? Qt.resolvedUrl("file://" + local) : ""
                                sourceSize: Qt.size(40, 40)
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                        }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            Label { text: name; width: 250; elide: Text.ElideRight; color: "#222222"; font.pixelSize: 13 }
                            Label { text: count + "首"; color: "#8E8E93"; font.pixelSize: 11; visible: kind !== "create" }
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            if (kind === "create")
                                createDialog.open()
                            else {
                                appBridge.collectTo(-1, itemId)
                                collectPopup.close()
                            }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: createDialog
        title: "创建新歌单"
        modal: true
        width: 280
        standardButtons: Dialog.Ok | Dialog.Cancel
        x: (parent.width - width) / 2
        y: 80
        TextField {
            id: playlistName
            width: parent.width
            placeholderText: "歌单名称"
            selectByMouse: true
        }
        onAccepted: {
            appBridge.createAndCollect(playlistName.text)
            playlistName.text = ""
            collectPopup.close()
        }
    }

    Popup {
        id: moreMenu
        parent: playBar
        width: 148
        height: 164
        x: playBar.width - width - 8
        y: -height - 6
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: "#FFFFFF"
            radius: 8
            border.color: "#E6E6E8"
        }
        function popup() { open() }
        Column {
            anchors.fill: parent
            spacing: 0
            Repeater {
                model: [
                    { icon: "document-save-symbolic", text: "下载", action: "download" },
                    { icon: "mail-send-symbolic", text: "分享", action: "share" },
                    { icon: "media-seek-forward-symbolic", text: "播放倍速", action: "rate" },
                    { icon: "avatar-default-symbolic", text: "歌手", action: "artist" },
                    { icon: "media-optical-symbolic", text: "专辑", action: "album" }
                ]
                delegate: Item {
                    width: 140
                    height: 30
                    Rectangle {
                        anchors.fill: parent
                        radius: 4
                        color: moreMouse.containsMouse ? "#FDECEC" : "transparent"
                    }
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8
                        Image { width: 16; height: 16; source: "image://icon/" + modelData.icon; sourceSize: Qt.size(16, 16); anchors.verticalCenter: parent.verticalCenter }
                        Label { text: modelData.text; color: "#333333"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                    }
                    MouseArea {
                        id: moreMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            moreMenu.close()
                            if (modelData.action === "download")
                                appBridge.enqueueDownload(-1)
                            else if (modelData.action === "share")
                                appBridge.copyShare()
                            else if (modelData.action === "rate")
                                appBridge.cycleRate()
                            else if (modelData.action === "artist")
                                appBridge.openCurrentArtist()
                            else if (modelData.action === "album")
                                appBridge.openCurrentAlbum()
                        }
                    }
                }
            }
        }
    }
    QtObject {
        id: qualityMenu
        property string model: ""
    }
}
