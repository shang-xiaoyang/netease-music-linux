import QtQuick 2.12
import QtQuick.Controls 2.12
import QtQuick.Layouts 1.12
import QtGraphicalEffects 1.12
import QtQml 2.12
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
    property var searchItem: searchBox
    property bool suggestPressed: false
    property bool blurSearch: false
    onBlurSearchChanged: if (blurSearch) { blurSearch = false; leaveSearch() }
    property bool searchWanted: false
    property string suggestText: ""
    property string searchHistory: ""
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
    property real positionAnchor: 0
    property real positionAt: 0
    property real playRate: 1
    property var navModel: typeof navList !== "undefined" ? navList : null
    property var cardModel: typeof cardList !== "undefined" ? cardList : null
    property var songModel: typeof songList !== "undefined" ? songList : null
    property var albumModel: typeof albumList !== "undefined" ? albumList : null
    property var eventModel: typeof eventList !== "undefined" ? eventList : null
    property var commentModel: typeof commentList !== "undefined" ? commentList : null
    property var downloadModel: typeof downloadList !== "undefined" ? downloadList : null
    property string loginKey: ""
    property string detailName: ""
    property string detailSub: ""
    property string detailBrief: ""
    property string detailCover: ""
    property string artistTab: "songs"
    property string lyricText: "歌词加载中…"
    property string currentSongId: ""
    property string currentArtists: ""
    property bool playlistOwned: false
    property bool playlistCollected: false
    property int playlistSpecial: 0
    property string playlistCreator: ""
    property string playlistCreatorId: ""

    function clock(ms) {
        var value = Math.max(0, Math.floor(Number(ms || 0) / 1000))
        var min = Math.floor(value / 60)
        var sec = value % 60
        return (min < 10 ? "0" : "") + min + ":" + (sec < 10 ? "0" : "") + sec
    }

    // 桥把信号写进这些属性。属性变化在 Qt 5.12 和 5.15 上都能接到，
    // Connections 的两种写法各只能用一边。
    property string bridgeStatus: ""
    property string bridgeSuggest: ""
    property string bridgeState: ""
    property string bridgeClock: ""
    property string bridgeSong: ""
    property string bridgePage: ""
    property string bridgeAccount: ""
    property string bridgeMode: ""
    property string bridgeRate: ""
    property string bridgeQuality: ""
    property string bridgeVolume: ""
    property string bridgeCover: ""
    property string bridgeDetail: ""
    property string bridgeLyric: ""
    property string bridgeArtistTab: ""
    property string bridgeHistory: ""
    property string bridgeLoginKey: ""
    property string bridgeQualities: ""
    property string bridgeLiked: ""
    property string bridgeCurrentSong: ""
    property string bridgePlaylistMeta: ""
    onBridgeStatusChanged: status.text = bridgeStatus
    onBridgeSuggestChanged: window.suggestText = bridgeSuggest || ""
    onBridgeStateChanged: {
        window.playing = bridgeState === "playing"
        window.positionAnchor = window.position
        window.positionAt = Date.now()
    }
    onBridgeClockChanged: {
        var parts = bridgeClock.split(",")
        window.position = Number(parts[0])
        window.duration = Number(parts[1])
        window.positionAnchor = window.position
        window.positionAt = Date.now()
    }
    onBridgeSongChanged: {
        var parts = bridgeSong.split("\n")
        window.songTitle = parts[1] || ""
        window.songArtist = parts[2] || ""
        window.songAlbum = parts[6] || ""
        window.duration = Number(parts[4] || 0)
        window.currentArtists = parts[5] || ""
        if (parts[0] !== window.currentSongId) {
            window.currentSongId = parts[0] || ""
            window.position = 0
            window.positionAnchor = 0
            window.positionAt = Date.now()
        }
        window.playing = false
    }
    onBridgePageChanged: {
        var parts = bridgePage.split("\n")
        window.pageName = parts[0] || ""
        window.pageTitle = parts.slice(1).join("\n")
        if (window.pageName === "list" || window.pageName === "playlist")
            window.listReset = window.listReset + 1
    }
    onBridgeAccountChanged: account.text = bridgeAccount
    onBridgeModeChanged: window.modeText = bridgeMode
    onBridgeRateChanged: {
        window.positionAnchor = window.position
        window.positionAt = Date.now()
        window.playRate = Number(bridgeRate)
    }
    onBridgeQualityChanged: window.qualityText = bridgeQuality
    onBridgeVolumeChanged: window.volume = Number(bridgeVolume)
    onBridgeCoverChanged: window.coverPath = bridgeCover
    onBridgeDetailChanged: {
        if (bridgeDetail.indexOf("cover\n") === 0) {
            window.detailCover = bridgeDetail.slice(6)
            return
        }
        var parts = bridgeDetail.split("\n")
        window.detailName = parts[0] || ""
        window.detailSub = parts[1] || ""
        window.detailBrief = parts.slice(2).join("\n")
        window.detailCover = ""
    }
    onBridgeLyricChanged: window.lyricText = bridgeLyric
    onBridgeArtistTabChanged: window.artistTab = bridgeArtistTab || "songs"
    onBridgeHistoryChanged: window.searchHistory = bridgeHistory || ""
    onBridgeLoginKeyChanged: window.loginKey = bridgeLoginKey
    onBridgeQualitiesChanged: qualityMenu.model = bridgeQualities
    onBridgeLikedChanged: window.liked = bridgeLiked === "1"
    onBridgeCurrentSongChanged: window.currentSongId = bridgeCurrentSong
    onBridgePlaylistMetaChanged: {
        var parts = (bridgePlaylistMeta || "").split("|")
        window.playlistOwned = parts[0] === "1"
        window.playlistCollected = parts[1] === "1"
        window.playlistSpecial = Number(parts[2] || 0)
        window.playlistCreatorId = parts[3] || ""
        window.playlistCreator = parts.slice(4).join("|")
    }

    Rectangle {
        id: titleBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 52
        color: "#FFFFFF"
        radius: window.visibility === 4 ? 0 : 12
        z: 50
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#E6E6E8"
        }
        RowLayout {
            id: searchRow
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
            Item { Layout.fillWidth: true; Layout.minimumWidth: 12 }
            Rectangle {
                id: searchBox
                Layout.fillWidth: true
                Layout.minimumWidth: 120
                Layout.maximumWidth: 320
                Layout.preferredHeight: 32
                Layout.alignment: Qt.AlignVCenter
                radius: 16
                color: "#F5F5F7"
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
                        placeholderText: "搜索歌曲、歌手、歌单"
                        selectByMouse: true
                        // 标题栏有一层用来拖动窗口的 MouseArea。按下时自己取得焦点，点击才进得了输入框。
                        activeFocusOnPress: true
                        background: Item {}
                        leftPadding: 0
                        rightPadding: 0
                        property int suggestToken: 0
                        onTextChanged: queueSuggest()
                        onActiveFocusChanged: if (activeFocus) queueSuggest()
                        function queueSuggest() {
                            suggestToken = suggestToken + 1
                            var typed = text
                            if (typed.trim() === "") {
                                window.suggestText = ""
                                return
                            }
                            suggestTimer.token = suggestToken
                            suggestTimer.typed = typed
                            suggestTimer.restart()
                        }
                        onAccepted: {
                            suggestTimer.stop()
                            window.suggestText = ""
                            window.searchHistory = prependHistory(window.searchHistory, text)
                            appBridge.search(text)
                            leaveSearch()
                        }
                        function prependHistory(current, keyword) {
                            var text = keyword.trim()
                            if (text === "")
                                return current
                            var rows = current === "" ? [] : current.split("\n")
                            var next = [text]
                            for (var i = 0; i < rows.length && next.length < 10; i++) {
                                if (rows[i] !== "" && rows[i] !== text)
                                    next.push(rows[i])
                            }
                            return next.join("\n")
                        }
                        function openSuggestion(fields) {
                            suggestTimer.stop()
                            window.suggestText = ""
                            window.searchHistory = prependHistory(window.searchHistory, fields[1] || text)
                            appBridge.playSuggestion(fields[0] || "", fields[1] || text, fields[2] || "")
                            leaveSearch()
                        }
                        Keys.onEscapePressed: handleEscape()
                        Keys.onDownPressed: if (suggestPopup.visible && suggestView.count > 0) suggestView.currentIndex = 0
                        Timer {
                            id: suggestTimer
                            interval: 280
                            property int token: 0
                            property string typed: ""
                            onTriggered: {
                                if (token !== search.suggestToken)
                                    return
                                appBridge.suggest(typed)
                            }
                        }
                    }
                }
            }
            Item { Layout.fillWidth: true; Layout.minimumWidth: 12 }
            Button {
                id: account
                text: "登录"
                flat: true
                clip: true
                Layout.maximumWidth: 140
                Layout.preferredWidth: Math.min(140, implicitWidth)
                contentItem: Label {
                    text: account.text
                    color: "#333333"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
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
            id: titleDrag
            anchors.fill: parent
            z: -1
            acceptedButtons: Qt.LeftButton
            propagateComposedEvents: true
            property real grabX: 0
            property real grabY: 0
            property bool dragging: false
            onDoubleClicked: window.visibility === 4 ? window.showNormal() : window.showMaximized()
            onPressed: {
                var searchPoint = searchBox.mapFromItem(titleBar, mouse.x, mouse.y)
                var accountPoint = account.mapFromItem(titleBar, mouse.x, mouse.y)
                var onSearch = searchPoint.x >= 0 && searchPoint.x <= searchBox.width && searchPoint.y >= 0 && searchPoint.y <= searchBox.height
                var onAccount = accountPoint.x >= 0 && accountPoint.x <= account.width && accountPoint.y >= 0 && accountPoint.y <= account.height
                // 下拉层画在标题栏下面，但父级是窗口。点在层上时不要当成拖窗口。
                var popPoint = suggestPopup.mapFromItem(titleBar, mouse.x, mouse.y)
                var onPopup = suggestPopup.visible && popPoint.x >= 0 && popPoint.x <= suggestPopup.width && popPoint.y >= 0 && popPoint.y <= suggestPopup.height
                if (onSearch || onAccount || onPopup) {
                    dragging = false
                    mouse.accepted = false
                } else {
                    leaveSearch()
                    // 记下指针相对窗口的位置。全局坐标在这个系统上会跟着窗口一起变，不能拿来算位移。
                    grabX = mouse.x
                    grabY = mouse.y + titleBar.y
                    dragging = window.visibility !== 4
                }
            }
            onPositionChanged: {
                if (!dragging)
                    return
                var cursor = titleBar.mapToGlobal(mouse.x, mouse.y)
                window.x = cursor.x - grabX
                window.y = cursor.y - grabY
            }
            onReleased: dragging = false
        }
    }

    Item {
        anchors.top: titleBar.bottom
        anchors.bottom: playColumn.top
        anchors.left: parent.left
        anchors.right: parent.right

        MouseArea {
            anchors.fill: parent
            z: -1
            onPressed: {
                if (suggestPopup.visible || search.activeFocus)
                    leaveSearch()
                mouse.accepted = false
            }
        }

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
                cacheBuffer: 400
                delegate: Item {
                    width: nav.width
                    height: kind === "section" ? 28 : 34
                    Rectangle {
                        anchors.fill: parent
                        color: kind === "section" ? "transparent" : (mouse.containsMouse && !nav.moving ? "#E8F3FF" : (window.pageTitle === label ? "#FDECEC" : "transparent"))
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
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: {
                            if (mouse.button === Qt.RightButton && (kind === "playlist" || kind === "liked")) {
                                navMenuState.open(key, label, kind, owned)
                                return
                            }
                            appBridge.openNav(key)
                        }
                    }
                }
            }
            QtObject {
                id: navMenuState
                property string key: ""
                property string label: ""
                property string kind: ""
                property bool owned: false
                function open(key, label, kind, owned) {
                    navMenuState.key = key
                    navMenuState.label = label
                    navMenuState.kind = kind
                    navMenuState.owned = owned
                    navMenu.popup()
                }
            }
            Menu {
                id: navMenu
                MenuItem {
                    text: "▶  播放"
                    onTriggered: appBridge.openNav(navMenuState.key)
                }
                MenuItem {
                    text: "⏭  下一首播放"
                    onTriggered: appBridge.playNavNext(navMenuState.key)
                }
                MenuItem {
                    text: "✎  重命名"
                    visible: navMenuState.owned
                    height: visible ? implicitHeight : 0
                    onTriggered: {
                        renameField.text = navMenuState.label
                        renameDialog.open()
                    }
                }
                MenuItem {
                    text: "✕  删除歌单"
                    visible: navMenuState.owned
                    height: visible ? implicitHeight : 0
                    onTriggered: appBridge.deleteNavPlaylist(navMenuState.key)
                }
                MenuItem {
                    text: "✕  取消收藏"
                    visible: navMenuState.kind === "playlist" && !navMenuState.owned
                    height: visible ? implicitHeight : 0
                    onTriggered: appBridge.unsubscribeNav(navMenuState.key)
                }
            }
            Dialog {
                id: renameDialog
                parent: window.contentItem
                title: "重命名歌单"
                modal: true
                standardButtons: Dialog.Ok | Dialog.Cancel
                x: (window.width - width) / 2
                y: 120
                width: 280
                TextField {
                    id: renameField
                    width: renameDialog.availableWidth
                    placeholderText: "歌单名称"
                    selectByMouse: true
                    maximumLength: 40
                }
                onAccepted: appBridge.renameNavPlaylist(navMenuState.key, renameField.text)
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
                RotationAnimator {
                    target: disc
                    from: 0
                    to: 360
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
                    cacheBuffer: 240
                    property int lineAt: {
                        // 新歌词还没到时只有占位行。这时不能拿上一首残留的进度去对，否则会来回停在同一行。
                        if (window.lyricText === "")
                            return 0
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
                currentIndex: window.pageName === "discover" ? 1 : window.pageName === "list" ? 2 : window.pageName === "playlist" ? 3 : window.pageName === "album" ? 4 : window.pageName === "artist" ? 5 : window.pageName === "lyric" ? 6 : window.pageName === "comments" ? 7 : window.pageName === "user" ? 8 : window.pageName === "downloads" ? 9 : 0

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
                    contentHeight: discoverColumn.implicitHeight + 24
                    clip: true
                    visible: window.pageName === "discover"
                    Column {
                        id: discoverColumn
                        width: parent.width
                        Row {
                            visible: window.pageTitle.indexOf("歌单「") === 0
                            leftPadding: 22
                            topPadding: 8
                            spacing: 18
                            Label {
                                text: "单曲"
                                color: "#8E8E93"
                                font.pixelSize: 14
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: appBridge.searchTab("songs")
                                }
                            }
                            Label {
                                text: "歌单"
                                color: "#EC4141"
                                font.pixelSize: 14
                                font.bold: true
                            }
                        }
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
                                    Row {
                                        width: 120
                                        spacing: 0
                                        Label {
                                            text: creator || ""
                                            width: Math.min(implicitWidth, creator ? 72 : 0)
                                            visible: creator !== ""
                                            elide: Text.ElideRight
                                            color: creatorHover.containsMouse ? "#EC4141" : "#507DAF"
                                            font.pixelSize: 11
                                            MouseArea {
                                                id: creatorHover
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: appBridge.openUser(creatorId, creator)
                                                ToolTip.visible: containsMouse
                                                ToolTip.text: "打开作者：" + creator
                                                ToolTip.delay: 300
                                            }
                                        }
                                        Label {
                                            text: (creator ? " · " : "") + count + " 首"
                                            color: "#8E8E93"
                                            font.pixelSize: 11
                                        }
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    z: -1
                                    onClicked: appBridge.openPlaylist(itemId, name)
                                }
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
                Loader {
                    active: window.pageName === "playlist"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: playlistPage
                }
                QtObject {
                    id: songMenuState
                    property int row: -1
                    function open(row) {
                        songMenuState.row = row
                        removeTrackItem.visible = appBridge.canRemoveCurrent()
                        appBridge.openCollect()
                        songMenu.popup()
                    }
                }
                Menu {
                    id: songMenu
                    MenuItem {
                        text: "⏭  下一首播放"
                        enabled: (songList.get(songMenuState.row) || {}).playable !== false
                        onTriggered: appBridge.playNext(songMenuState.row)
                    }
                    MenuItem {
                        text: (appBridge.songLiked((songList.get(songMenuState.row) || {}).songId) ? "♥  取消喜欢" : "♡  加入喜欢")
                        onTriggered: appBridge.toggleLike(songMenuState.row)
                    }
                    MenuItem {
                        text: "↓  下载"
                        enabled: (songList.get(songMenuState.row) || {}).playable !== false
                        onTriggered: appBridge.enqueueDownload(songMenuState.row)
                    }
                    MenuItem { text: "✎  查看评论"; onTriggered: appBridge.openComments(songMenuState.row) }
                    MenuItem {
                        id: removeTrackItem
                        text: "✕  从当前歌单移除"
                        visible: false
                        height: visible ? implicitHeight : 0
                        onTriggered: appBridge.removeFromPlaylist(songMenuState.row)
                    }
                    Menu {
                        id: collectMenu
                        title: "收藏到歌单"
                        Instantiator {
                            model: collectList
                            delegate: MenuItem {
                                text: name
                                visible: kind !== "create"
                                height: visible ? implicitHeight : 0
                                onTriggered: appBridge.collectTo(songMenuState.row, itemId)
                            }
                            onObjectAdded: collectMenu.insertItem(index, object)
                            onObjectRemoved: collectMenu.removeItem(object)
                        }
                    }
                }
                Component {
                    id: songPage
                ListView {
                    id: songView
                    objectName: "songView"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    cacheBuffer: 480
                    header: Column {
                        id: songColumn
                        width: songView.width
                        spacing: 0
                    Row {
                        leftPadding: 16
                        topPadding: 4
                        height: window.pageTitle.indexOf("搜索") === 0 ? 28 : 0
                        visible: window.pageTitle.indexOf("搜索") === 0
                        spacing: 18
                        Label {
                            text: "单曲"
                            color: "#EC4141"
                            font.pixelSize: 14
                            font.bold: true
                        }
                        Label {
                            text: "歌单"
                            color: "#8E8E93"
                            font.pixelSize: 14
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: appBridge.searchTab("playlists")
                            }
                        }
                    }
                    }
                    model: window.songModel
                    onContentYChanged: {
                        if (contentHeight - contentY - height < 240)
                            appBridge.moreSongs()
                    }
                    property int resetWatch: window.listReset
                    onResetWatchChanged: contentY = 0
                    property int menuRow: -1
                    property var artistPeople: []
                    function openArtists(people) {
                        artistPeople = people
                        artistMenu.popup()
                    }
                    Menu {
                        id: artistMenu
                        Instantiator {
                            model: songView.artistPeople
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
                    function openRowMenu(row) {
                        menuRow = row
                        songMenuState.open(row)
                    }
                    delegate: ItemDelegate {
                        width: songView.width
                        height: 56
                        opacity: model.playable === false ? 0.38 : 1
                        onDoubleClicked: if (model.playable !== false) appBridge.playRow(index)
                        onPressAndHold: songView.openRowMenu(index)
                        background: Rectangle {
                            color: model.songId === window.currentSongId ? "#FDECEC" : (parent.hovered && !songView.moving ? "#E8F3FF" : "transparent")
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.RightButton
                            onClicked: songView.openRowMenu(index)
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
                                        songView.openArtists(people)
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

                Component {
                    id: playlistPage
                    ListView {
                        id: playlistSongs
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        cacheBuffer: 480
                        header: Column {
                            id: playlistColumn
                            width: playlistSongs.width
                            spacing: 8
                            topPadding: 8
                        Rectangle {
                            width: parent.width
                            height: playlistIntro.implicitHeight + 28
                            color: "#FFFFFF"
                            Row {
                            id: playlistIntro
                            leftPadding: 16
                            rightPadding: 16
                            topPadding: 14
                            width: parent.width
                            spacing: 16
                            Rectangle {
                                width: 132
                                height: 132
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
                                width: parent.width - 180
                                spacing: 6
                                anchors.verticalCenter: parent.verticalCenter
                                Label {
                                    text: window.detailName || window.pageTitle
                                    color: "#222222"
                                    font.pixelSize: 20
                                    font.bold: true
                                    width: parent.width
                                    elide: Text.ElideRight
                                }
                                Row {
                                    width: parent.width
                                    spacing: 0
                                    visible: window.playlistCreator !== "" || window.detailSub !== ""
                                    Label {
                                        id: playlistCreatorLink
                                        text: window.playlistCreator
                                        visible: text !== ""
                                        color: playlistCreatorHit.containsMouse ? "#EC4141" : "#507DAF"
                                        font.pixelSize: 13
                                        MouseArea {
                                            id: playlistCreatorHit
                                            enabled: window.playlistCreatorId !== ""
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                            onClicked: appBridge.openUser(window.playlistCreatorId, window.playlistCreator)
                                            ToolTip.visible: containsMouse && enabled
                                            ToolTip.text: "打开作者：" + window.playlistCreator
                                            ToolTip.delay: 300
                                        }
                                    }
                                    Label {
                                        text: {
                                            var sub = window.detailSub || ""
                                            if (window.playlistCreator === "")
                                                return sub
                                            var prefix = window.playlistCreator + " · "
                                            return sub.indexOf(prefix) === 0 ? sub.slice(prefix.length) : ""
                                        }
                                        color: "#8E8E93"
                                        font.pixelSize: 13
                                        elide: Text.ElideRight
                                        width: Math.max(0, parent.width - playlistCreatorLink.implicitWidth)
                                    }
                                }
                                Label {
                                    text: window.detailBrief
                                    color: "#666666"
                                    font.pixelSize: 12
                                    wrapMode: Text.Wrap
                                    width: parent.width
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                    visible: text !== ""
                                }
                                Row {
                                    spacing: 10
                                    topPadding: 6
                                    Rectangle {
                                        width: playAllLabel.implicitWidth + 28
                                        height: 32
                                        radius: 16
                                        color: playAllHover.containsMouse ? "#D73333" : "#EC4141"
                                        Label {
                                            id: playAllLabel
                                            anchors.centerIn: parent
                                            text: "播放全部"
                                            color: "#FFFFFF"
                                            font.pixelSize: 13
                                        }
                                        MouseArea {
                                            id: playAllHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: appBridge.playAll()
                                        }
                                    }
                                    Rectangle {
                                        width: playNextLabel.implicitWidth + 28
                                        height: 32
                                        radius: 16
                                        color: playNextHover.containsMouse ? "#FDECEC" : "#FFFFFF"
                                        border.color: "#EC4141"
                                        Label {
                                            id: playNextLabel
                                            anchors.centerIn: parent
                                            text: "下一首播放"
                                            color: "#EC4141"
                                            font.pixelSize: 13
                                        }
                                        MouseArea {
                                            id: playNextHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: appBridge.playListNext()
                                        }
                                    }
                                    Rectangle {
                                        visible: !window.playlistOwned && window.playlistSpecial !== 5
                                        width: visible ? collectLabel.implicitWidth + 28 : 0
                                        height: visible ? 32 : 0
                                        radius: 16
                                        color: collectHover.containsMouse ? (window.playlistCollected ? "#FDECEC" : "#F7F7F8") : "#FFFFFF"
                                        border.color: window.playlistCollected ? "#EC4141" : "#D8D8DC"
                                        Label {
                                            id: collectLabel
                                            anchors.centerIn: parent
                                            text: window.playlistCollected ? "已收藏" : "收藏歌单"
                                            color: window.playlistCollected ? "#EC4141" : "#333333"
                                            font.pixelSize: 13
                                        }
                                        MouseArea {
                                            id: collectHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: appBridge.toggleSubscribe()
                                        }
                                    }
                                }
                            }
                            }
                        }
                        }
                        model: window.songModel
                        onContentYChanged: {
                            if (contentHeight - contentY - height < 240)
                                appBridge.moreSongs()
                        }
                        property int resetWatch: window.listReset
                        onResetWatchChanged: contentY = 0
                        delegate: ItemDelegate {
                                width: playlistSongs.width
                                height: 56
                                opacity: model.playable === false ? 0.38 : 1
                                onDoubleClicked: if (model.playable !== false) appBridge.playRow(index)
                                onPressAndHold: songMenuState.open(index)
                                background: Rectangle {
                                    color: model.songId === window.currentSongId ? "#FDECEC" : (parent.hovered ? "#E8F3FF" : "transparent")
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    acceptedButtons: Qt.RightButton
                                    onClicked: songMenuState.open(index)
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
                                    Label { text: model.artist || ""; color: "#8E8E93"; Layout.preferredWidth: 140; elide: Text.ElideRight }
                                    Label { text: clock(model.duration); color: "#8E8E93"; Layout.preferredWidth: 48 }
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
                Flickable {
                    id: albumFlick
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: width
                    contentHeight: albumColumn.implicitHeight + 24
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    Column {
                        id: albumColumn
                        width: albumFlick.width
                        spacing: 12
                        topPadding: 8
                    Rectangle {
                        width: parent.width
                        height: albumIntro.implicitHeight + 28
                        color: "#FFFFFF"
                    Row {
                        id: albumIntro
                        leftPadding: 16
                        rightPadding: 16
                        topPadding: 14
                        width: parent.width
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
                            width: parent.width - 218
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
                    }
                    Repeater {
                        id: detailSongs
                        model: window.songModel
                        delegate: ItemDelegate {
                            width: albumColumn.width
                            height: 48
                            opacity: model.playable === false ? 0.38 : 1
                            onDoubleClicked: if (model.playable !== false) appBridge.playRow(index)
                            onPressAndHold: songMenuState.open(index)
                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.RightButton
                                onClicked: songMenuState.open(index)
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
                }

                Loader {
                    active: window.pageName === "artist"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: artistPage
                }
                Component {
                    id: artistPage
                    Flickable {
                        id: artistFlick
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: width
                        contentHeight: artistColumn.implicitHeight + 24
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        Column {
                            id: artistColumn
                            width: artistFlick.width
                            spacing: 12
                            topPadding: 8
                            Rectangle {
                                width: parent.width
                                height: artistIntro.implicitHeight + 16
                                color: "#FFFFFF"
                            Column {
                                id: artistIntro
                                width: parent.width
                                topPadding: 14
                                bottomPadding: 12
                                spacing: 10
                            Row {
                                leftPadding: 16
                                rightPadding: 16
                                width: parent.width
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
                                    width: parent.width - 182
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
                                }
                            }
                            }
                            }
                            Row {
                                id: artistTabs
                                leftPadding: 16
                                spacing: 8
                                topPadding: 4
                                property var tabs: [
                                    { key: "home", text: "主页" },
                                    { key: "songs", text: "歌曲" },
                                    { key: "albums", text: "专辑" },
                                    { key: "blog", text: "博客" }
                                ]
                                Repeater {
                                    model: artistTabs.tabs
                                    delegate: Rectangle {
                                        width: tabLabel.implicitWidth + 28
                                        height: 30
                                        radius: 15
                                        color: window.artistTab === modelData.key ? "#EC4141" : (tabHover.containsMouse ? "#FDECEC" : "#FFFFFF")
                                        border.color: window.artistTab === modelData.key ? "#EC4141" : "#E6E6E8"
                                        Label {
                                            id: tabLabel
                                            anchors.centerIn: parent
                                            text: modelData.text
                                            color: window.artistTab === modelData.key ? "#FFFFFF" : "#333333"
                                            font.pixelSize: 13
                                        }
                                        MouseArea {
                                            id: tabHover
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: appBridge.setArtistTab(modelData.key)
                                        }
                                    }
                                }
                            }
                            Item {
                                width: parent.width
                                height: artistHome.implicitHeight
                                visible: window.artistTab === "home"
                                Column {
                                    id: artistHome
                                    width: parent.width
                                    leftPadding: 16
                                    rightPadding: 16
                                    spacing: 8
                                    Label {
                                        text: window.detailBrief !== "" ? window.detailBrief : "这个歌手还没有介绍"
                                        color: "#666666"
                                        font.pixelSize: 13
                                        wrapMode: Text.Wrap
                                        width: parent.width - 32
                                    }
                                }
                            }
                            Column {
                                width: parent.width
                                visible: window.artistTab === "songs"
                                spacing: 0
                                Label {
                                    text: artistSongs.count > 0 ? "热门 " + artistSongs.count + " 首" : "还没有歌曲"
                                    color: "#8E8E93"
                                    font.pixelSize: 12
                                    leftPadding: 16
                                    bottomPadding: 4
                                }
                                Repeater {
                                    id: artistSongs
                                    model: window.artistTab === "songs" ? window.songModel : null
                                    delegate: ItemDelegate {
                                        width: artistColumn.width
                                        height: 56
                                        opacity: model.playable === false ? 0.38 : 1
                                        onDoubleClicked: if (model.playable !== false) appBridge.playRow(index)
                                        onPressAndHold: songMenuState.open(index)
                                        background: Rectangle {
                                            color: model.songId === window.currentSongId ? "#FDECEC" : (parent.hovered ? "#E8F3FF" : "transparent")
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            acceptedButtons: Qt.RightButton
                                            onClicked: songMenuState.open(index)
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
                                            Label {
                                                text: model.album || ""
                                                color: "#507DAF"
                                                Layout.preferredWidth: 160
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
                                            Label { text: clock(model.duration); color: "#8E8E93"; Layout.preferredWidth: 48 }
                                        }
                                    }
                                }
                            }
                            Flow {
                                width: parent.width - 32
                                x: 16
                                visible: window.artistTab === "albums"
                                spacing: 16
                                Repeater {
                                    model: window.artistTab === "albums" ? window.albumModel : null
                                    delegate: Item {
                                        width: 120
                                        height: 176
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
                                                    source: model.local ? Qt.resolvedUrl("file://" + model.local) : ""
                                                    sourceSize: Qt.size(120, 120)
                                                    fillMode: Image.PreserveAspectCrop
                                                    asynchronous: true
                                                }
                                            }
                                            Label {
                                                text: model.name || ""
                                                width: 120
                                                color: "#333333"
                                                font.pixelSize: 13
                                                elide: Text.ElideRight
                                            }
                                            Label {
                                                text: model.publish || ""
                                                width: 120
                                                color: "#8E8E93"
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: appBridge.openAlbum(model.itemId, model.name)
                                        }
                                    }
                                }
                            }
                            Label {
                                visible: window.artistTab === "albums" && albumList.count === 0
                                text: "还没有专辑"
                                color: "#8E8E93"
                                font.pixelSize: 13
                                leftPadding: 16
                            }
                            Column {
                                width: parent.width
                                visible: window.artistTab === "blog"
                                spacing: 0
                                Repeater {
                                    model: window.artistTab === "blog" ? window.eventModel : null
                                    delegate: Item {
                                        width: artistColumn.width
                                        height: Math.max(eventBody.implicitHeight + 24, model.local ? 92 : 0)
                                        Row {
                                            id: eventBody
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.leftMargin: 16
                                            anchors.rightMargin: 16
                                            anchors.top: parent.top
                                            anchors.topMargin: 12
                                            spacing: 12
                                            Rectangle {
                                                width: model.local ? 96 : 0
                                                height: model.local ? 64 : 0
                                                radius: 6
                                                color: "#F3D6D6"
                                                clip: true
                                                visible: model.local !== ""
                                                Image {
                                                    anchors.fill: parent
                                                    source: model.local ? Qt.resolvedUrl("file://" + model.local) : ""
                                                    sourceSize: Qt.size(96, 64)
                                                    fillMode: Image.PreserveAspectCrop
                                                    asynchronous: true
                                                }
                                            }
                                            Column {
                                                width: parent.width - (model.local ? 108 : 0)
                                                spacing: 4
                                                Label {
                                                    text: model.title || ""
                                                    color: "#222222"
                                                    font.pixelSize: 14
                                                    font.bold: true
                                                    wrapMode: Text.Wrap
                                                    width: parent.width
                                                }
                                                Label {
                                                    text: model.summary || ""
                                                    color: "#666666"
                                                    font.pixelSize: 12
                                                    wrapMode: Text.Wrap
                                                    width: parent.width
                                                    maximumLineCount: 2
                                                    elide: Text.ElideRight
                                                    visible: text !== ""
                                                }
                                                Label {
                                                    text: (model.when || "") + (model.read && model.read !== "0" ? "    阅读 " + model.read : "")
                                                    color: "#8E8E93"
                                                    font.pixelSize: 11
                                                    visible: text !== ""
                                                }
                                            }
                                        }
                                        Rectangle {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.leftMargin: 16
                                            anchors.bottom: parent.bottom
                                            height: 1
                                            color: "#E6E6E8"
                                        }
                                    }
                                }
                                Label {
                                    visible: eventList.count === 0
                                    text: "还没有博客"
                                    color: "#8E8E93"
                                    font.pixelSize: 13
                                    leftPadding: 16
                                    topPadding: 8
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

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.topMargin: 8
                        Layout.preferredHeight: 32
                        Label {
                            text: "文件保存在「音乐 / 网易云音乐」。这里只列出本机下载过的歌曲。"
                            color: "#8E8E93"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Button {
                            text: "打开文件夹"
                            flat: true
                            onClicked: appBridge.openDownloadFolder()
                        }
                    }
                    Label {
                        visible: downloadView.count === 0
                        text: "还没有下载。在歌曲上右键选择「下载」，完成后会出现在这里。"
                        color: "#8E8E93"
                        font.pixelSize: 14
                        Layout.fillWidth: true
                        Layout.topMargin: 48
                        horizontalAlignment: Text.AlignHCenter
                    }
                    ListView {
                        id: downloadView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: window.downloadModel
                        clip: true
                        header: Item {
                            width: downloadView.width
                            height: 28
                            visible: downloadView.count > 0
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                Label { text: "歌曲"; color: "#8E8E93"; font.pixelSize: 12; Layout.fillWidth: true }
                                Label { text: "状态"; color: "#8E8E93"; font.pixelSize: 12; Layout.preferredWidth: 88 }
                                Label { text: "音质"; color: "#8E8E93"; font.pixelSize: 12; Layout.preferredWidth: 120 }
                                Label { text: "文件"; color: "#8E8E93"; font.pixelSize: 12; Layout.preferredWidth: 180 }
                            }
                        }
                        delegate: Item {
                            width: downloadView.width
                            height: 40
                            Rectangle {
                                anchors.fill: parent
                                color: index % 2 === 0 ? "transparent" : "#FAFAFB"
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                Label { text: name; Layout.fillWidth: true; elide: Text.ElideRight; color: "#333333" }
                                Label {
                                    text: status
                                    color: status === "完成" ? "#3C9D5B" : (String(status).indexOf("失败") === 0 ? "#EC4141" : "#8E8E93")
                                    Layout.preferredWidth: 88
                                    elide: Text.ElideRight
                                }
                                Label { text: quality; color: "#8E8E93"; Layout.preferredWidth: 120; elide: Text.ElideRight }
                                Label { text: path; color: "#8E8E93"; Layout.preferredWidth: 180; elide: Text.ElideRight }
                            }
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
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
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
        Timer {
            interval: 500
            running: window.playing && window.duration > 0
            repeat: true
            onTriggered: {
                var next = window.positionAnchor + (Date.now() - window.positionAt) * window.playRate
                window.position = Math.min(window.duration, Math.max(0, next))
            }
        }
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
            onShowQueue: {
                if (queuePopup.visible) {
                    queuePopup.close()
                    return
                }
                playBar.closeFloats()
                queuePopup.open()
                centerQueue.restart()
            }
            onToggleLike: appBridge.toggleLike(-1)
            onOpenComments: appBridge.openComments(-1)
            onCollect: {
                playBar.closeFloats()
                appBridge.openCollect()
                collectPopup.open()
            }
            onOpenMore: {
                playBar.closeFloats()
                moreMenu.popup()
            }
            onDismissPopups: window.closeFloats()
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

    function closeFloats() {
        moreMenu.close()
        accountPopup.close()
        queuePopup.close()
        collectPopup.close()
        if (suggestPopup.visible)
            leaveSearch()
    }

    function leaveSearch() {
        suggestTimer.stop()
        window.suggestText = ""
        search.deselect()
        search.focus = false
        keySink.forceActiveFocus()
    }

    function handleEscape() {
        if (suggestPopup.visible) {
            window.suggestText = ""
            search.forceActiveFocus()
            return
        }
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

    Timer {
        id: centerQueue
        interval: 1
        repeat: false
        onTriggered: queueView.centerCurrent()
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
        onOpened: centerQueue.restart()
        background: Rectangle {
            color: "#FFFFFF"
            radius: 8
            border.color: "#E6E6E8"
        }
        ListView {
            id: queueView
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            model: queueList
            boundsBehavior: Flickable.StopAtBounds
            property int menuRow: -1
            function openRowMenu(row) {
                menuRow = row
                queueMenu.popup()
            }
            Menu {
                id: queueMenu
                MenuItem {
                    text: "⏭  下一首播放"
                    enabled: (queueList.get(queueView.menuRow) || {}).playable !== false
                    onTriggered: appBridge.playNextQueue(queueView.menuRow)
                }
                MenuItem {
                    text: (appBridge.songLiked((queueList.get(queueView.menuRow) || {}).songId) ? "♥  取消喜欢" : "♡  加入喜欢")
                    onTriggered: appBridge.toggleQueueLike(queueView.menuRow)
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
                            onTriggered: appBridge.collectQueue(queueView.menuRow, itemId)
                        }
                        onObjectAdded: queueCollect.insertItem(index, object)
                        onObjectRemoved: queueCollect.removeItem(object)
                    }
                }
                MenuItem {
                    text: "✕  从播放列表移除"
                    onTriggered: {
                        queueView.removingRow = true
                        appBridge.removeFromQueue(queueView.menuRow)
                        queueView.removingRow = false
                    }
                }
            }
            property int playingRow: {
                var playing = window.currentSongId
                var rows = count
                if (!playing || rows < 1)
                    return -1
                var found = -1
                for (var i = 0; i < rows; i++) {
                    if (String((queueList.get(i) || {}).songId || "") !== playing)
                        continue
                    if (found < 0)
                        found = i
                    // 同一首歌可能被插成「下一首」。当前正在播的那一行优先。
                    if (i === appBridge.queueIndex())
                        return i
                }
                return found
            }
            onPlayingRowChanged: if (!removingRow) centerQueue.restart()
            property bool removingRow: false
            function centerCurrent() {
                var row = playingRow
                if (!queuePopup.visible || row < 0 || count < 1)
                    return
                positionViewAtIndex(row, ListView.Center)
            }
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
                opacity: model.playable === false ? 0.38 : 1
                Rectangle {
                    anchors.fill: parent
                    color: model.songId === window.currentSongId ? "#FDECEC" : (hover.containsMouse && !queueView.moving ? "#F6F6F8" : "transparent")
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
                        if (mouse.button === Qt.RightButton) {
                            appBridge.openCollect()
                            queueView.openRowMenu(index)
                        }
                    }
                    onDoubleClicked: {
                        if (mouse.button === Qt.LeftButton && model.playable !== false)
                            appBridge.playQueue(index)
                    }
                    onPressAndHold: {
                        appBridge.openCollect()
                        queueView.openRowMenu(index)
                    }
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

    // 不用 Popup。无边框窗口里它的坐标会偏到左侧，点击也会漏到下面的页面。
    // mapToItem 不会跟着布局更新，第一次算出的 x 会停在 0。直接加标题行和搜索框的 x。
    // 放在窗口内容的最后，盖住标题栏和页面，点击才不会穿到下面的歌单。
    Item {
        id: suggestPopup
        parent: window.contentItem
        z: 200
        x: searchRow.x + searchBox.x
        y: searchRow.y + searchBox.y + searchBox.height + 4
        width: Math.max(searchBox.width, 280)
        height: search.text.trim() === ""
            ? (historyView.count > 0 ? historyView.count * 32 + 40 : 0)
            : Math.min(8, suggestView.count) * 36 + 36
        visible: search.activeFocus && (
            (search.text.trim() !== "" && window.suggestText !== "")
            || (search.text.trim() === "" && historyView.count > 0)
        )
        Rectangle {
            anchors.fill: parent
            radius: 8
            color: "#FFFFFF"
            border.color: "#E6E6E8"
        }
        MouseArea {
            anchors.fill: parent
            z: -1
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
            onPressed: mouse.accepted = true
        }
        ListView {
            id: historyView
            anchors.fill: parent
            anchors.margins: 4
            visible: search.text.trim() === ""
            clip: true
            model: window.searchHistory === "" ? [] : window.searchHistory.split("\n")
            header: Item {
                width: historyView.width
                height: 32
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    text: "搜索历史"
                    color: "#8E8E93"
                    font.pixelSize: 12
                }
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    text: "清空"
                    color: "#507DAF"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: appBridge.clearSearchHistory()
                    }
                }
            }
            delegate: Item {
                width: historyView.width
                height: 32
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: historyHover.containsMouse ? "#F4F4F6" : "transparent"
                }
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    width: parent.width - 24
                    text: modelData
                    color: "#333333"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
                MouseArea {
                    id: historyHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        search.text = modelData
                        search.accepted()
                    }
                }
            }
        }
        ListView {
            id: suggestView
            anchors.fill: parent
            anchors.margins: 4
            visible: search.text.trim() !== ""
            clip: true
            model: window.suggestText === "" ? [] : window.suggestText.split("\n")
            keyNavigationWraps: false
            header: Item {
                width: suggestView.width
                height: 32
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    text: "搜索「" + search.text + "」"
                    color: "#507DAF"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    width: parent.width - 24
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: search.accepted()
                }
            }
            delegate: Item {
                width: suggestView.width
                height: 36
                property var fields: String(modelData).split("\t")
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: suggestHover.containsMouse || (suggestView.activeFocus && index === suggestView.currentIndex) ? "#F4F4F6" : "transparent"
                }
                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    width: parent.width - 24
                    text: (fields[1] || "") + (fields[2] ? "  ·  " + fields[2] : "")
                    color: "#333333"
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
                MouseArea {
                    id: suggestHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: search.openSuggestion(fields)
                }
                Keys.onReturnPressed: search.openSuggestion(fields)
                Keys.onEnterPressed: search.openSuggestion(fields)
            }
        }
    }

    QtObject {
        id: qualityMenu
        property string model: ""
    }

    property bool resizing: false
    property int resizeEdges: 0
    property real resizeX0: 0
    property real resizeY0: 0
    property real resizeW0: 0
    property real resizeH0: 0
    property real resizePX: 0
    property real resizePY: 0

    function beginResize(edge, global) {
        if (visibility === 4)
            return
        resizing = true
        resizeEdges = edge
        resizeX0 = x
        resizeY0 = y
        resizeW0 = width
        resizeH0 = height
        resizePX = global.x
        resizePY = global.y
    }

    function moveResize(global) {
        if (!resizing)
            return
        var dx = global.x - resizePX
        var dy = global.y - resizePY
        var nx = resizeX0
        var ny = resizeY0
        var nw = resizeW0
        var nh = resizeH0
        if (resizeEdges & Qt.LeftEdge) {
            nw = Math.max(minimumWidth, resizeW0 - dx)
            nx = resizeX0 + resizeW0 - nw
        }
        if (resizeEdges & Qt.RightEdge)
            nw = Math.max(minimumWidth, resizeW0 + dx)
        if (resizeEdges & Qt.TopEdge) {
            nh = Math.max(minimumHeight, resizeH0 - dy)
            ny = resizeY0 + resizeH0 - nh
        }
        if (resizeEdges & Qt.BottomEdge)
            nh = Math.max(minimumHeight, resizeH0 + dy)
        x = nx
        y = ny
        width = nw
        height = nh
    }

    // 无边框窗口没有系统缩放边。只铺在四边，不挡住标题按钮和列表。
    Item {
        id: resizeFrame
        anchors.fill: parent
        z: 30
        enabled: window.visibility !== 4
        visible: enabled

        ResizeGrip { edge: Qt.LeftEdge; width: 6; anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.topMargin: 8; anchors.bottomMargin: 8 }
        ResizeGrip { edge: Qt.RightEdge; width: 6; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.topMargin: 8; anchors.bottomMargin: 8 }
        ResizeGrip { edge: Qt.TopEdge; height: 6; anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right; anchors.leftMargin: 8; anchors.rightMargin: 8 }
        ResizeGrip { edge: Qt.BottomEdge; height: 6; anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; anchors.leftMargin: 8; anchors.rightMargin: 8 }
        ResizeGrip { edge: Qt.LeftEdge | Qt.TopEdge; width: 8; height: 8; anchors.left: parent.left; anchors.top: parent.top }
        ResizeGrip { edge: Qt.RightEdge | Qt.TopEdge; width: 8; height: 8; anchors.right: parent.right; anchors.top: parent.top }
        ResizeGrip { edge: Qt.LeftEdge | Qt.BottomEdge; width: 8; height: 8; anchors.left: parent.left; anchors.bottom: parent.bottom }
        ResizeGrip { edge: Qt.RightEdge | Qt.BottomEdge; width: 8; height: 8; anchors.right: parent.right; anchors.bottom: parent.bottom }
    }
}
