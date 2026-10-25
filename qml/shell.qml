import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtMultimedia

Item {
    id: app
    property var stateData: ({items: [], fonts: [], palette: {}, active: "", resolution: [1920,1080]})
    property var palette: stateData.palette || ({})
    property color bg: palette.background || "#101114"
    property color surface: palette.surface || "#191b20"
    property color raised: palette.raised || "#22252b"
    property color fg: palette.foreground || "#e6e8ef"
    property color muted: palette.muted || "#8c929f"
    property color accent: palette.accent || "#a9b8d0"
    property color edge: palette.border || "#353841"
    property string page: "library"
    property string selectedId: ""
    property var selected: null
    property bool busy: true
    property bool polling: false
    property var libraryItems: []
    property bool failed: false
    property int percent: 0
    property string message: "Загрузка библиотеки…"
    property string fontQuery: ""
    property bool playing: false
    property bool ready: false
    property string backendError: ""
    ListModel { id: fontsModel }
    onFontQueryChanged: syncFonts()

    function syncFonts() {
        var desired = (stateData.fonts || []).filter(item => item.name.toLowerCase().indexOf(fontQuery) !== -1);
        for (var i = 0; i < desired.length; ++i) {
            var item = desired[i];
            if (i >= fontsModel.count || fontsModel.get(i).fontName !== item.name) {
                var existing = -1;
                for (var j = i + 1; j < fontsModel.count; ++j) {
                    if (fontsModel.get(j).fontName === item.name) { existing = j; break; }
                }
                if (existing >= 0) fontsModel.move(existing, i, 1);
                else fontsModel.insert(i, {fontName: item.name, fontTitle: item.title, fontEnabled: item.enabled});
            }
            if (fontsModel.get(i).fontEnabled !== item.enabled) fontsModel.setProperty(i, "fontEnabled", item.enabled);
            if (fontsModel.get(i).fontTitle !== item.title) fontsModel.setProperty(i, "fontTitle", item.title);
        }
        if (fontsModel.count > desired.length) fontsModel.remove(desired.length, fontsModel.count - desired.length);
    }

    function send(action, payload) {
        if (busy) return;
        if (action === "state" && polling) return;
        var request = payload || {};
        request.action = action;
        if (action === "state") polling = true;
        else {
            busy = true;
            failed = false;
            percent = 0;
            message = "Выполняется…";
        }
        NativeBackend.send(JSON.stringify(request));
    }
    function select(item) {
        playing = false;
        selectedId = item.id;
        selected = item;
    }
    function updateSelection() {
        var items = stateData.items || [];
        var wanted = selectedId || stateData.active;
        var found = null;
        for (var i = 0; i < items.length; ++i) if (items[i].id === wanted) found = items[i];
        var next = found || (items.length ? items[0] : null);
        if (JSON.stringify(selected) !== JSON.stringify(next)) selected = next;
        selectedId = selected ? selected.id : "";
    }
    function screenSize() {
        // Backend prefers the focused physical Hyprland output. QML is a fallback.
        if (stateData.resolution_fixed) return null;
        var screens = stateData.monitors || [];
        if (screens.length) return null;
        if (stateData.resolution && settingsFixed.checked) return stateData.resolution;
        var ratio = win.screen ? win.screen.devicePixelRatio : 1;
        if (!ratio || !isFinite(ratio)) ratio = 1;
        return [Math.round((win.screen ? win.screen.width : 1920) * ratio), Math.round((win.screen ? win.screen.height : 1080) * ratio)];
    }
    function receive(line) {
        try {
            var event = JSON.parse(line);
            if (event.type === "progress") { busy = true; percent = event.percent; message = event.message; }
            else if (event.type === "error") {
                if (event.action === "state") polling = false;
                else busy = false;
                failed = true; message = event.message;
            }
            else if (event.type === "notice") { message = event.message; }
            else if (event.type === "state") {
                if (JSON.stringify(stateData) !== JSON.stringify(event.state)) {
                    stateData = event.state;
                    if (JSON.stringify(libraryItems) !== JSON.stringify(stateData.items || [])) libraryItems = stateData.items || [];
                    syncFonts();
                    updateSelection();
                }
                if (event.action === "state") polling = false;
                else busy = false;
                ready = true;
                if (event.message) { message = event.message; failed = false; }
                else if (!failed && message === "Загрузка библиотеки и превью…") message = "Выбери фон или добавь своё видео";
            }
        } catch (error) { failed = true; message = "Ошибка ответа приложения: " + error; busy = false; }
    }

    Connections {
        target: NativeBackend
        function onEvent(line) { app.receive(line); }
    }
    Component.onCompleted: NativeBackend.start()
    function testPolling() {
        if (grid.count < 1 || fontsModel.count < 1) return false;
        grid.forceLayout();
        var card = grid.itemAtIndex(0);
        var selection = selected;
        send("state");
        if (busy || !polling) return false;
        receive(JSON.stringify({type: "state", action: "state", state: JSON.parse(JSON.stringify(stateData))}));
        grid.forceLayout();
        if (busy || polling || grid.itemAtIndex(0) !== card || selected !== selection) return false;
        var refreshed = JSON.parse(JSON.stringify(stateData));
        refreshed.fonts[0].enabled = !refreshed.fonts[0].enabled;
        receive(JSON.stringify({type: "state", action: "state", state: refreshed}));
        grid.forceLayout();
        return grid.itemAtIndex(0) === card;
    }
    function testFonts() {
        if (fontsModel.count <= 20) return false;
        fontList.positionViewAtIndex(20, ListView.Center);
        fontList.forceLayout();
        var before = fontList.contentY;
        var row = fontList.itemAtIndex(20);
        var refreshed = JSON.parse(JSON.stringify(stateData));
        refreshed.fonts[20].enabled = !refreshed.fonts[20].enabled;
        receive(JSON.stringify({type: "state", state: refreshed}));
        fontList.forceLayout();
        return page === "fonts" && Math.abs(fontList.contentY - before) <= 0.5 && fontList.itemAtIndex(20) === row;
    }
    Timer {
        interval: 12000
        running: app.ready
        repeat: true
        onTriggered: if (!app.busy && !app.polling) app.send("state")
    }
    FileDialog {
        id: addVideo
        title: "Добавить видеофон"
        nameFilters: ["Видео (*.mp4 *.webm *.mkv *.mov *.m4v *.avi)", "Все файлы (*)"]
        onAccepted: {
            var path = NativeBackend.localPath(String(selectedFile));
            app.send("add", {path: path, size: app.screenSize()});
        }
    }
    FolderDialog {
        id: chooseGame
        title: "Папка dota 2 beta или game"
        onAccepted: app.send("settings", {game: NativeBackend.localPath(String(selectedFolder))})
    }
    FolderDialog {
        id: chooseBase
        title: "Папка основы фона"
        onAccepted: app.send("settings", {template: NativeBackend.localPath(String(selectedFolder))})
    }

    ApplicationWindow {
        id: win
        title: "Wallpaper changer"
        visible: true
        objectName: "mainWindow"
        width: 1240
        height: 820
        minimumWidth: 1000
        minimumHeight: 680
        onClosing: close => {
            if (app.busy) {
                close.accepted = false;
                app.message = "Дождитесь завершения операции перед закрытием.";
            }
        }
        color: app.bg
        // Standard Qt window on Windows, Linux and Wayland.
        Item {
            id: canvas
            anchors.fill: parent
            RowLayout {
                anchors.fill: parent
                spacing: 0
                Rectangle {
                    Layout.preferredWidth: 196
                    Layout.fillHeight: true
                    color: app.surface
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10
                        Text {
                            text: "WALLPAPER\nCHANGER"
                            font.family: "Noto Sans"
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            font.letterSpacing: 2
                            lineHeight: 1.35
                            color: app.fg
                            horizontalAlignment: Text.AlignHCenter
                            Layout.fillWidth: true
                            Layout.topMargin: 4
                        }
                        Item { Layout.preferredHeight: 30 }
                        Repeater {
                            model: [{key:"library", label:"Библиотека", symbol:"◫"}, {key:"fonts", label:"Шрифты Dota", symbol:"Aa"}, {key:"settings", label:"Настройки", symbol:"⌘"}]
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 44
                                radius: 8
                                color: app.page === modelData.key ? app.raised : navHover.hovered ? Qt.rgba(app.fg.r, app.fg.g, app.fg.b, 0.04) : "transparent"
                                border.color: app.page === modelData.key ? app.edge : "transparent"
                                RowLayout {
                                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 10; spacing: 12
                                    Text { text: modelData.symbol; color: app.page === modelData.key ? app.fg : app.muted; font.pixelSize: 17; Layout.preferredWidth: 22 }
                                    Text { text: modelData.label; color: app.page === modelData.key ? app.fg : app.muted; font.family: "Noto Sans"; font.pixelSize: 12; font.weight: Font.Medium; Layout.fillWidth: true }
                                }
                                HoverHandler { id: navHover }
                                TapHandler { onTapped: { app.playing = false; app.page = modelData.key; } }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        Rectangle { visible: !!app.palette.omarchy; Layout.fillWidth: true; height: 1; color: app.edge }
                        Text { visible: !!app.palette.omarchy; text: "OMARCHY"; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 9; font.letterSpacing: 1.5; Layout.topMargin: 12 }
                        RowLayout {
                            visible: !!app.palette.omarchy
                            Rectangle { width: 8; height: 8; radius: 4; color: app.accent }
                            Text { text: app.palette.name || "Системная тема"; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                        }
                    }
                }
                Rectangle { width: 1; Layout.fillHeight: true; color: app.edge }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.margins: 28
                    spacing: 20
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text { text: app.page === "library" ? "Твоё главное меню" : app.page === "fonts" ? "Шрифты внутри Dota 2" : "Всё под контролем"; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 26; font.weight: Font.DemiBold }
                            Text { text: app.page === "library" ? "Выбери фон. Или добавь видео — остальное сделаем сами." : app.page === "fonts" ? "Включай и отключай шрифты. Оригиналы сохраняются для восстановления." : "Интеграция с Omarchy, экран и восстановление"; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        }
                        ActionButton {
                            visible: app.page === "library"
                            text: "+  Добавить видео"
                            primary: true; ink: app.bg; fill: app.fg; outline: app.fg
                            enabled: !app.busy
                            onClicked: addVideo.open()
                        }
                    }

                    Rectangle {
                        visible: app.page === "library" && !!app.stateData.game_installed && (!!app.stateData.scene_needs_update || !app.stateData.mount_ready || !!app.stateData.obsolete_launch_option)
                        Layout.fillWidth: true
                        implicitHeight: sceneBanner.implicitHeight + 24
                        color: app.raised; radius: 10; border.color: app.edge
                        RowLayout {
                            id: sceneBanner
                            anchors.fill: parent; anchors.margins: 12
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 4
                                Text { text: app.stateData.mount_ready ? "Нужно обновить подключение фона" : "Фон лежит в папке, которую игра не загружает"; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 12; font.bold: true }
                                Text { text: "Исправление обновит фикс и установит его в штатную языковую папку."; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11 }
                            }
                            ActionButton { text: "Исправить"; ink: app.fg; fill: app.surface; outline: app.edge; enabled: !app.busy; onClicked: app.send("repair") }
                        }
                    }

                    RowLayout {
                        visible: app.page === "library"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 22
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                            RowLayout {
                                Text { text: "КОЛЛЕКЦИЯ"; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 10; font.letterSpacing: 1.4; Layout.fillWidth: true }
                                Text { text: (app.stateData.items || []).length + " фонов"; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11 }
                            }
                            GridView {
                                id: grid
                                Layout.fillWidth: true; Layout.fillHeight: true
                                clip: true
                                cellWidth: width / Math.max(2, Math.floor(width / 220))
                                cellHeight: cellWidth * 0.5625 + 66
                                model: app.libraryItems
                                ScrollBar.vertical: ScrollBar { }
                                delegate: Item {
                                    required property var modelData
                                    width: grid.cellWidth; height: grid.cellHeight
                                    Rectangle {
                                        anchors.fill: parent; anchors.rightMargin: 12; anchors.bottomMargin: 12
                                        color: app.surface; radius: 10
                                        border.width: app.selectedId === modelData.id ? 2 : 1
                                        border.color: app.selectedId === modelData.id ? app.accent : cardHover.hovered ? app.muted : app.edge
                                        Column {
                                            anchors.fill: parent; anchors.margins: 8; spacing: 10
                                            Image { width: parent.width; height: width * 0.5625; source: modelData.preview_url; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: true }
                                            Row {
                                                width: parent.width; spacing: 6
                                                Rectangle { visible: app.stateData.active === modelData.id; width: 6; height: 6; radius: 3; color: app.accent; anchors.verticalCenter: parent.verticalCenter }
                                                Text { width: parent.width - 20; text: modelData.title; elide: Text.ElideRight; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 12 }
                                            }
                                        }
                                        HoverHandler { id: cardHover }
                                        TapHandler { onTapped: app.select(modelData) }
                                    }
                                }
                            }
                            Text { visible: !(app.stateData.items || []).length; text: "Здесь будут твои видеофоны. Нажми +, чтобы добавить первый."; color: app.muted; font.family: "Noto Sans"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        }
                        Rectangle {
                            Layout.preferredWidth: 300
                            Layout.fillHeight: true
                            color: app.surface; radius: 12; border.color: app.edge
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 16; spacing: 14
                                Text { text: "ПРЕДПРОСМОТР"; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 10; font.letterSpacing: 1.4 }
                                Rectangle {
                                    Layout.fillWidth: true; Layout.preferredHeight: width * 0.5625; color: app.bg; radius: 6; clip: true
                                    Image { anchors.fill: parent; source: app.selected ? app.selected.preview_url : ""; fillMode: Image.PreserveAspectCrop; visible: !app.playing }
                                    VideoOutput { id: videoOutput; anchors.fill: parent; fillMode: VideoOutput.Stretch; visible: app.playing }
                                    MediaPlayer {
                                        id: player
                                        source: app.selected ? app.selected.video_url : ""
                                        videoOutput: videoOutput
                                        loops: MediaPlayer.Infinite
                                    }
                                    Connections {
                                        target: app
                                        function onPlayingChanged() { if (app.playing) player.play(); else player.stop(); }
                                        function onSelectedIdChanged() { player.stop(); }
                                    }
                                }
                                Text { text: app.selected ? app.selected.title : "Выбери фон"; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 18; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                Text { text: app.selected ? app.selected.media.width + " × " + app.selected.media.height + "  ·  " + Number(app.selected.media.duration).toFixed(1) + " с" : ""; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11 }
                                Text { text: app.selected && app.stateData.active === app.selected.id ? "● Сейчас установлен" : "Готов к применению"; color: app.accent; font.family: "Noto Sans"; font.pixelSize: 11 }
                                ActionButton { Layout.fillWidth: true; text: app.playing ? "Остановить превью" : "Смотреть видео"; ink: app.fg; fill: app.raised; outline: app.edge; enabled: !!app.selected; onClicked: app.playing = !app.playing }
                                Item { Layout.fillHeight: true }
                                Text { text: "Автоматически под экран\nMP4 → WebM · без чёрных полос\n" + (app.stateData.scene_fix && app.stateData.scene_fix.event_name ? "Фикс: " + app.stateData.scene_fix.event_name : "Фикс текущего события включён"); color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11; lineHeight: 1.7; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                ActionButton { Layout.fillWidth: true; text: "Применить фон"; primary: true; ink: app.bg; fill: app.fg; outline: app.fg; enabled: !!app.selected && !app.busy; onClicked: app.send("activate", {id: app.selectedId, size: app.screenSize()}) }
                            }
                        }
                    }

                    ColumnLayout {
                        visible: app.page === "fonts"
                        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 14
                        TextField { id: fontSearch; placeholderText: "Найти шрифт…"; placeholderTextColor: app.muted; implicitHeight: 40; padding: 12; Layout.fillWidth: true; color: app.fg; font.family: "Noto Sans"; onTextChanged: app.fontQuery = text.toLowerCase(); background: Rectangle { color: app.surface; radius: 8; border.color: app.edge } }
                        ListView {
                            id: fontList
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8
                            model: fontsModel
                            ScrollBar.vertical: ScrollBar { }
                            delegate: Rectangle {
                                id: fontRow
                                required property string fontName
                                required property string fontTitle
                                required property bool fontEnabled
                                width: ListView.view.width; height: 72; radius: 10; color: app.surface; border.color: app.edge
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 16; spacing: 16
                                    Text { text: "Aa"; color: app.muted; font.family: "Noto Serif"; font.pixelSize: 28; Layout.preferredWidth: 48 }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 4
                                        Text { text: fontRow.fontTitle; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 13; font.weight: Font.Medium }
                                        Text { text: fontRow.fontName; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 10 }
                                    }
                                    Text { text: fontRow.fontEnabled ? "Включён" : "Отключён · копия сохранена"; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11 }
                                    Switch {
                                        id: fontSwitch
                                        checked: fontRow.fontEnabled; enabled: !app.busy
                                        onClicked: {
                                            var requested = checked;
                                            app.send("font", {name: fontRow.fontName, enabled: requested});
                                            // The backend owns the saved state, including failed operations.
                                            checked = Qt.binding(function() { return fontRow.fontEnabled; });
                                        }
                                        indicator: Rectangle {
                                            implicitWidth: 42; implicitHeight: 24; radius: 12
                                            x: fontSwitch.leftPadding; y: (fontSwitch.height - height) / 2
                                            color: fontSwitch.checked ? app.accent : app.raised
                                            border.color: fontSwitch.checked ? app.accent : app.muted
                                            opacity: fontSwitch.enabled ? 1 : 0.4
                                            Rectangle {
                                                width: 18; height: 18; radius: 9; y: 3
                                                x: fontSwitch.checked ? parent.width - width - 3 : 3
                                                color: fontSwitch.checked ? app.bg : app.muted
                                                Behavior on x { NumberAnimation { duration: 140 } }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        Text { text: "Изменения применяются после перезапуска Dota 2. Проверка файлов Steam может вернуть отключённые шрифты."; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }

                    ScrollView {
                        visible: app.page === "settings"
                        Layout.fillWidth: true; Layout.fillHeight: true
                        contentWidth: availableWidth
                        ColumnLayout {
                            width: parent.width; spacing: 20
                            Rectangle {
                                Layout.fillWidth: true; implicitHeight: options.implicitHeight + 36; color: app.surface; radius: 12; border.color: app.edge
                                ColumnLayout {
                                    id: options; anchors.fill: parent; anchors.margins: 18; spacing: 12
                                    Text { text: "Экран и оформление"; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 16; font.bold: true }
                                    Text { visible: !!app.palette.omarchy; text: "Тема Omarchy: " + (app.palette.name || ""); color: app.muted; font.family: "Noto Sans"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    Text { text: "Видео растягивается до физического разрешения выбранного экрана.\nТекущее разрешение: " + (app.stateData.resolution || []).join(" × "); color: app.muted; font.family: "Noto Sans"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    CheckBox { id: settingsFixed; text: "Использовать фиксированное разрешение"; checked: !!app.stateData.resolution_fixed; palette.windowText: app.fg; palette.text: app.fg }
                                    RowLayout {
                                        TextField { id: screenWidth; text: String((app.stateData.resolution || [1920,1080])[0]); color: app.fg; padding: 10; implicitHeight: 40; Layout.preferredWidth: 100; inputMethodHints: Qt.ImhDigitsOnly; background: Rectangle { color: app.raised; radius: 6; border.color: app.edge } }
                                        Text { text: "×"; color: app.muted }
                                        TextField { id: screenHeight; text: String((app.stateData.resolution || [1920,1080])[1]); color: app.fg; padding: 10; implicitHeight: 40; Layout.preferredWidth: 100; inputMethodHints: Qt.ImhDigitsOnly; background: Rectangle { color: app.raised; radius: 6; border.color: app.edge } }
                                        ActionButton { text: "Сохранить"; ink: app.fg; fill: app.raised; outline: app.edge; enabled: !app.busy; onClicked: app.send("settings", {resolution: settingsFixed.checked ? [Number(screenWidth.text),Number(screenHeight.text)] : null}) }
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true; implicitHeight: recovery.implicitHeight + 36; color: app.surface; radius: 12; border.color: app.edge
                                ColumnLayout {
                                    id: recovery; anchors.fill: parent; anchors.margins: 18; spacing: 12
                                    Text { text: "Игра и восстановление"; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 16; font.bold: true }
                                    Text { text: "Дополнительные параметры запуска не нужны. Старый -language 123 удаляется при установке.\nИспользуется штатная папка аудиоязыка; язык текста сохраняется."; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    RowLayout {
                                        ActionButton { text: "Обновить фикс события"; ink: app.fg; fill: app.raised; outline: app.edge; enabled: !app.busy && !!app.stateData.game_installed; onClicked: app.send("repair") }
                                        ActionButton { text: "Отключить фон"; ink: app.fg; fill: app.raised; outline: app.edge; enabled: !app.busy && !!app.stateData.game_installed; onClicked: app.send("disable") }
                                        ActionButton { text: "Обновить библиотеку"; ink: app.fg; fill: app.raised; outline: app.edge; enabled: !app.busy; onClicked: app.send("rescan") }
                                    }
                                }
                            }
                            ToolButton {
                                id: advancedToggle
                                property bool expanded: false
                                text: expanded ? "−  Подробности и пути" : "+  Подробности и пути"
                                palette.buttonText: app.muted
                                onClicked: expanded = !expanded
                            }
                            ColumnLayout {
                                visible: advancedToggle.expanded; Layout.fillWidth: true; spacing: 10
                                Text { text: "Игра: " + (app.stateData.game || "не найдена"); color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                Text { text: "Основа: " + (app.stateData.template || "не найдена"); color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                Text { text: "Папка загрузки: " + (app.stateData.mount_folder || "пока не подключена") + "\nАудиоязык: " + ((app.stateData.language || {}).audio || "не определён"); color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                Text { text: app.stateData.scene_fix ? "Заменена ссылка на сцену:\n" + app.stateData.scene_fix.event_scene + "\nФикс собран из текущего dashboard.vxml_c. Проверяется запуском игры." : "Актуальный фикс ещё не установлен."; color: app.muted; font.family: "Noto Sans"; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                RowLayout {
                                    ActionButton { text: "Выбрать игру"; ink: app.fg; fill: app.surface; outline: app.edge; enabled: !app.busy; onClicked: chooseGame.open() }
                                    ActionButton { text: "Выбрать основу"; ink: app.fg; fill: app.surface; outline: app.edge; enabled: !app.busy; onClicked: chooseBase.open() }
                                }
                            }
                            Item { Layout.preferredHeight: 20 }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: statusRow.implicitHeight + 24
                        color: app.surface; radius: 10; border.color: app.failed ? app.muted : app.edge
                        ColumnLayout {
                            id: statusRow
                            anchors.fill: parent; anchors.margins: 12; spacing: 8
                            RowLayout {
                                Rectangle { width: 7; height: 7; radius: 3.5; color: app.busy ? app.accent : app.muted }
                                Text { text: app.message; color: app.failed ? app.fg : app.muted; font.family: "Noto Sans"; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                Text { visible: app.busy; text: app.percent + "%"; color: app.fg; font.family: "Noto Sans"; font.pixelSize: 11 }
                            }
                            Rectangle {
                                visible: app.busy; Layout.fillWidth: true; height: 3; radius: 2; color: app.edge
                                Rectangle { width: Math.max(8, parent.width * app.percent / 100); height: parent.height; radius: 2; color: app.accent; Behavior on width { NumberAnimation { duration: 200 } } }
                            }
                        }
                    }
                }
            }
        }
    }
}
