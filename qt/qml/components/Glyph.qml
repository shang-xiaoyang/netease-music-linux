import QtQuick 2.15

Canvas {
    id: glyph
    width: 16
    height: 16
    property string kind: "play"
    property bool active: false
    property color ink: "#222222"

    onKindChanged: requestPaint()
    onActiveChanged: requestPaint()
    onInkChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.clearRect(0, 0, width, height)
        ctx.fillStyle = ink
        ctx.strokeStyle = ink
        ctx.lineWidth = 1.4
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        if (kind === "play") {
            ctx.beginPath()
            ctx.moveTo(4, 2)
            ctx.lineTo(17, 10)
            ctx.lineTo(4, 18)
            ctx.closePath()
            ctx.fill()
        } else if (kind === "pause") {
            ctx.fillRect(4, 3, 4, 14)
            ctx.fillRect(12, 3, 4, 14)
        } else if (kind === "prev" || kind === "next") {
            var flip = kind === "next"
            ctx.save()
            if (flip)
                ctx.translate(width, 0), ctx.scale(-1, 1)
            ctx.beginPath()
            ctx.moveTo(3, 3)
            ctx.lineTo(3, 13)
            ctx.lineTo(11, 8)
            ctx.closePath()
            ctx.fill()
            ctx.fillRect(12, 3, 2, 10)
            ctx.restore()
        } else if (kind === "repeat") {
            ctx.beginPath()
            ctx.moveTo(4, 5)
            ctx.lineTo(11, 5)
            ctx.arc(11, 8, 3, -Math.PI / 2, Math.PI / 2, false)
            ctx.lineTo(5, 11)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(3, 3.2)
            ctx.lineTo(6.2, 5)
            ctx.lineTo(3, 6.8)
            ctx.closePath()
            ctx.fill()
        } else if (kind === "single") {
            ctx.font = "11px sans-serif"
            ctx.fillText("1", 5, 12)
        } else if (kind === "order") {
            ctx.beginPath()
            ctx.moveTo(3, 5)
            ctx.lineTo(12, 5)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(9, 2.5)
            ctx.lineTo(13, 5)
            ctx.lineTo(9, 7.5)
            ctx.closePath()
            ctx.fill()
        } else if (kind === "shuffle") {
            ctx.beginPath()
            ctx.moveTo(2, 4)
            ctx.lineTo(6, 4)
            ctx.lineTo(13, 12)
            ctx.moveTo(2, 12)
            ctx.lineTo(6, 12)
            ctx.lineTo(13, 4)
            ctx.stroke()
        } else if (kind === "heart") {
            ctx.beginPath()
            ctx.moveTo(8, 13.5)
            ctx.bezierCurveTo(2, 9.5, 1.5, 5.5, 4.2, 3.6)
            ctx.bezierCurveTo(6, 2.3, 7.6, 3, 8, 4.2)
            ctx.bezierCurveTo(8.4, 3, 10, 2.3, 11.8, 3.6)
            ctx.bezierCurveTo(14.5, 5.5, 14, 9.5, 8, 13.5)
            ctx.closePath()
            if (active)
                ctx.fill()
            else
                ctx.stroke()
        } else if (kind === "comment") {
            ctx.beginPath()
            ctx.moveTo(3.2, 4.2)
            ctx.lineTo(11.2, 4.2)
            ctx.arc(11.2, 6.2, 2, -Math.PI / 2, 0, false)
            ctx.lineTo(13.2, 8.2)
            ctx.arc(11.2, 8.2, 2, 0, Math.PI / 2, false)
            ctx.lineTo(8.2, 10.2)
            ctx.lineTo(6.4, 13.2)
            ctx.lineTo(6.2, 10.2)
            ctx.lineTo(4.8, 10.2)
            ctx.arc(4.8, 8.2, 1.6, Math.PI / 2, Math.PI, false)
            ctx.lineTo(3.2, 6.2)
            ctx.arc(4.8, 6.2, 1.6, Math.PI, Math.PI * 1.5, false)
            ctx.closePath()
            ctx.stroke()
            ctx.beginPath()
            ctx.arc(6.2, 7.2, 0.7, 0, Math.PI * 2)
            ctx.arc(8.4, 7.2, 0.7, 0, Math.PI * 2)
            ctx.arc(10.6, 7.2, 0.7, 0, Math.PI * 2)
            ctx.fill()
        } else if (kind === "plus") {
            ctx.strokeRect(2.2, 2.2, 11.6, 11.6)
            ctx.beginPath()
            ctx.moveTo(8, 4.5)
            ctx.lineTo(8, 11.5)
            ctx.moveTo(4.5, 8)
            ctx.lineTo(11.5, 8)
            ctx.stroke()
        } else if (kind === "list") {
            ctx.fillRect(2, 3, 2, 2)
            ctx.fillRect(2, 7, 2, 2)
            ctx.fillRect(2, 11, 2, 2)
            ctx.fillRect(6, 3.4, 8, 1.3)
            ctx.fillRect(6, 7.4, 8, 1.3)
            ctx.fillRect(6, 11.4, 8, 1.3)
        } else if (kind === "volume" || kind === "mute") {
            ctx.beginPath()
            ctx.moveTo(2, 6)
            ctx.lineTo(5, 6)
            ctx.lineTo(9, 3)
            ctx.lineTo(9, 13)
            ctx.lineTo(5, 10)
            ctx.lineTo(2, 10)
            ctx.closePath()
            ctx.fill()
            if (kind === "mute") {
                ctx.beginPath()
                ctx.moveTo(11, 6)
                ctx.lineTo(15, 10)
                ctx.moveTo(15, 6)
                ctx.lineTo(11, 10)
                ctx.stroke()
            } else {
                ctx.beginPath()
                ctx.arc(9, 8, 3.2, -0.8, 0.8, false)
                ctx.stroke()
            }
        } else if (kind === "more") {
            ctx.beginPath()
            ctx.arc(3.2, 8, 1.2, 0, Math.PI * 2)
            ctx.arc(8, 8, 1.2, 0, Math.PI * 2)
            ctx.arc(12.8, 8, 1.2, 0, Math.PI * 2)
            ctx.fill()
        } else if (kind === "min") {
            ctx.fillRect(3, 8, 10, 1.4)
        } else if (kind === "max") {
            ctx.strokeRect(3, 3, 10, 10)
        } else if (kind === "close") {
            ctx.beginPath()
            ctx.moveTo(4, 4)
            ctx.lineTo(12, 12)
            ctx.moveTo(12, 4)
            ctx.lineTo(4, 12)
            ctx.stroke()
        } else if (kind === "restore") {
            ctx.strokeRect(5, 3, 8, 8)
            ctx.strokeRect(3, 5, 8, 8)
        } else if (kind === "download") {
            ctx.beginPath()
            ctx.moveTo(8, 2)
            ctx.lineTo(8, 10)
            ctx.moveTo(5, 7)
            ctx.lineTo(8, 10)
            ctx.lineTo(11, 7)
            ctx.stroke()
            ctx.fillRect(3, 12, 10, 1.4)
        } else if (kind === "share") {
            ctx.beginPath()
            ctx.moveTo(4, 8)
            ctx.lineTo(12, 4)
            ctx.lineTo(12, 12)
            ctx.closePath()
            ctx.stroke()
        } else if (kind === "rate") {
            ctx.font = "11px sans-serif"
            ctx.fillText("×", 4, 12)
        } else if (kind === "artist") {
            ctx.beginPath()
            ctx.arc(8, 6, 2.4, 0, Math.PI * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.arc(8, 14, 4.2, Math.PI, 0, true)
            ctx.stroke()
        } else if (kind === "album") {
            ctx.beginPath()
            ctx.arc(8, 8, 5, 0, Math.PI * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.arc(8, 8, 1.4, 0, Math.PI * 2)
            ctx.fill()
        } else if (kind === "search") {
            ctx.beginPath()
            ctx.arc(6.5, 6.5, 3.4, 0, Math.PI * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(9, 9)
            ctx.lineTo(12.5, 12.5)
            ctx.stroke()
        }
    }
}
