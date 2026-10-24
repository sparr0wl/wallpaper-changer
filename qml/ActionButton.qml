import QtQuick
import QtQuick.Controls

Button {
    id: control
    property color ink: "#eeeeee"
    property color fill: "#242424"
    property color outline: "#454545"
    property bool primary: false
    implicitHeight: 40
    implicitWidth: Math.max(40, label.implicitWidth + 28)
    hoverEnabled: true
    opacity: enabled ? 1 : 0.4
    contentItem: Text {
        id: label
        text: control.text
        font.family: "Noto Sans"
        font.pixelSize: 13
        font.weight: control.primary ? Font.DemiBold : Font.Medium
        color: control.ink
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 8
        color: control.down ? Qt.lighter(control.fill, 1.35) : control.hovered ? Qt.lighter(control.fill, 1.18) : control.fill
        border.color: control.activeFocus ? control.ink : control.outline
        border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
