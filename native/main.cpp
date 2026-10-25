#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QProcess>
#include <QProcessEnvironment>
#include <QStandardPaths>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QTimer>
#include <QLocalServer>
#include <QLocalSocket>
#include <QCryptographicHash>
#include <QDebug>
#include <QScreen>
#include <iostream>
#ifdef Q_OS_WIN
#include <windows.h>
#endif

#ifndef WALLPAPER_SOURCE_DIR
#define WALLPAPER_SOURCE_DIR ""
#endif
#ifndef WALLPAPER_RELEASE
#define WALLPAPER_RELEASE "7.41f+Trove_of_Terror"
#endif

static QString codeDirectory() {
    const QDir app(QCoreApplication::applicationDirPath());
    const QString override = qEnvironmentVariable("WALLPAPER_CHANGER_CODE");
    const QStringList candidates{override, app.filePath("../lib/wallpaper-changer"), app.absolutePath(), QStringLiteral(WALLPAPER_SOURCE_DIR)};
    for (const auto &candidate : candidates)
        if (!candidate.isEmpty() && QFile::exists(QDir(candidate).filePath("dota_background/bridge.py")))
            return QDir(candidate).absolutePath();
    return {};
}

static bool configureBackend(QProcess &process, const QStringList &arguments = {}) {
    const QDir app(QCoreApplication::applicationDirPath());
    QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
    const QString tools = app.filePath("tools");
    environment.insert("PATH", tools + QDir::listSeparator() + environment.value("PATH"));
    environment.insert("PYTHONUTF8", "1");
    environment.insert("PYTHONIOENCODING", "utf-8");
    if (qobject_cast<QGuiApplication *>(QCoreApplication::instance())) {
        QJsonArray screens;
        for (auto *screen : QGuiApplication::screens()) {
            const QSize size = screen->size() * screen->devicePixelRatio();
            screens.append(QJsonObject{{"name", screen->name()}, {"width", size.width()},
                {"height", size.height()}, {"focused", screen == QGuiApplication::primaryScreen()}});
        }
        environment.insert("WALLPAPER_CHANGER_SCREENS", QString::fromUtf8(QJsonDocument(screens).toJson(QJsonDocument::Compact)));
    }
#ifdef Q_OS_WIN
    const QString frozen = app.filePath("_backend/wallpaper-backend.exe");
    process.setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments *args) { args->flags |= CREATE_NO_WINDOW; });
    if (QFile::exists(frozen)) {
        process.setProcessEnvironment(environment);
        process.setProgram(frozen);
        process.setArguments(arguments);
        return true;
    }
#endif
    const QString code = codeDirectory();
    QString python = qEnvironmentVariable("WALLPAPER_CHANGER_PYTHON");
    if (python.isEmpty()) python = QStandardPaths::findExecutable("python3");
    if (python.isEmpty()) python = QStandardPaths::findExecutable("python");
    if (code.isEmpty() || python.isEmpty()) return false;
    environment.insert("PYTHONPATH", code + QDir::listSeparator() + environment.value("PYTHONPATH"));
    process.setProcessEnvironment(environment);
    process.setProgram(python);
    if (arguments.contains("--self-test")) process.setArguments({"-m", "dota_background.self_test"});
    else process.setArguments({"-m", "dota_background.bridge"});
    return true;
}

class Backend final : public QObject {
    Q_OBJECT
public:
    explicit Backend(bool smoke, const QString &fixture, QObject *parent = nullptr) : QObject(parent), testMode(smoke || !fixture.isEmpty()) {
        if (!fixture.isEmpty()) {
            QFile file(fixture);
            if (!file.open(QIODevice::ReadOnly)) qFatal("Cannot open UI fixture");
            testState = QJsonDocument::fromJson(file.readAll()).object();
        } else if (smoke) {
            QJsonArray fonts;
            for (int i = 0; i < 40; ++i) fonts.append(QJsonObject{{"name", QString("font-%1.otf").arg(i)}, {"title", QString("Font %1").arg(i)}, {"enabled", true}});
            testState = QJsonObject{{"items", QJsonArray{}}, {"fonts", fonts}, {"palette", QJsonObject{}},
                {"active", ""}, {"resolution", QJsonArray{1920, 1080}}, {"monitors", QJsonArray{}}};
        }
        connect(&process, &QProcess::readyReadStandardOutput, this, [this] {
            pending += process.readAllStandardOutput();
            while (pending.contains('\n')) {
                const auto end = pending.indexOf('\n');
                const auto line = pending.left(end).trimmed();
                pending.remove(0, end + 1);
                if (!line.isEmpty()) emit event(QString::fromUtf8(line));
            }
        });
        connect(&process, &QProcess::readyReadStandardError, this, [this] { qWarning().noquote() << QString::fromUtf8(process.readAllStandardError()).trimmed(); });
        connect(&process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
            if (!closing && error == QProcess::FailedToStart) fail("Не удалось запустить службу приложения: " + process.errorString());
        });
        connect(&process, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this, [this](int code, QProcess::ExitStatus) {
            if (!closing) fail(QString("Служба остановлена (%1). Перезапустите приложение.").arg(code));
        });
    }
    ~Backend() override {
        closing = true;
        if (process.state() != QProcess::NotRunning) {
            process.closeWriteChannel();
            if (!process.waitForFinished(3000)) { process.terminate(); if (!process.waitForFinished(2000)) process.kill(); }
        }
    }
    Q_INVOKABLE void start() {
        if (started) return;
        started = true;
        if (testMode) { sendState({}); return; }
        if (!configureBackend(process)) { fail("Не найдена служба приложения или Python. Переустановите Wallpaper changer."); return; }
        process.start();
    }
    Q_INVOKABLE void send(const QString &line) {
        if (testMode) {
            const auto request = QJsonDocument::fromJson(line.toUtf8()).object();
            sendState(request.value("action").toString());
        } else if (process.state() == QProcess::Running) process.write(line.toUtf8() + '\n');
        else fail("Служба приложения недоступна");
    }
    Q_INVOKABLE QString localPath(const QString &url) const {
        const QUrl value(url);
        return value.isLocalFile() ? value.toLocalFile() : url;
    }
signals:
    void event(const QString &line);
private:
    void fail(const QString &message) { emit event(QString::fromUtf8(QJsonDocument(QJsonObject{{"type", "error"}, {"message", message}}).toJson(QJsonDocument::Compact))); }
    void sendState(const QString &action) {
        const QJsonObject value{{"type", "state"}, {"state", testState}, {"action", action}, {"message", "Выбери фон или добавь своё видео"}};
        QTimer::singleShot(0, this, [this, value] { emit event(QString::fromUtf8(QJsonDocument(value).toJson(QJsonDocument::Compact))); });
    }
    QProcess process;
    QByteArray pending;
    QJsonObject testState;
    bool testMode = false, started = false, closing = false;
};

int main(int argc, char **argv) {
    QStringList args;
    for (int i = 1; i < argc; ++i) args << QString::fromLocal8Bit(argv[i]);
    if (args.contains("--version")) { std::cout << "Wallpaper changer " << WALLPAPER_RELEASE << std::endl; return 0; }
    if (args.contains("--help") || args.contains("-h")) {
        std::cout << "Wallpaper changer\nUsage: wallpaper-changer [--version | --self-test | --smoke-test OUTPUT_DIRECTORY]\n"; return 0;
    }
    if (args.contains("--self-test")) {
        QCoreApplication app(argc, argv);
        QProcess process;
        if (!configureBackend(process, {"--self-test"})) return 2;
        process.setProcessChannelMode(QProcess::ForwardedChannels);
        process.start();
        if (!process.waitForStarted() || !process.waitForFinished(120000)) return 3;
        return process.exitCode();
    }
    const int smokeIndex = args.indexOf("--smoke-test");
    const bool smoke = smokeIndex >= 0;
    const int fixtureIndex = args.indexOf("--ui-test-state");
    const QString fixture = fixtureIndex >= 0 ? args.value(fixtureIndex + 1) : QString{};
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE")) qputenv("QT_QUICK_CONTROLS_STYLE", "Basic");
    QGuiApplication app(argc, argv);
    app.setApplicationName("wallpaper-changer");
    app.setApplicationDisplayName("Wallpaper changer");
    app.setApplicationVersion(WALLPAPER_RELEASE);
    app.setOrganizationName("sparr0wl");
    app.setDesktopFileName("wallpaper-changer");

    QLocalServer server;
    if (!smoke && fixture.isEmpty()) {
        const auto id = QCryptographicHash::hash(QDir::homePath().toUtf8(), QCryptographicHash::Sha256).toHex().left(16);
        const QString name = "wallpaper-changer-" + QString::fromLatin1(id);
        QLocalSocket socket;
        socket.connectToServer(name);
        if (socket.waitForConnected(200)) { socket.write("show"); socket.waitForBytesWritten(500); return 0; }
        QLocalServer::removeServer(name);
        if (!server.listen(name)) qWarning() << "Single-instance IPC unavailable:" << server.errorString();
    }
    Backend backend(smoke, fixture);
    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlEngine::quit, &app, &QCoreApplication::quit);
    engine.rootContext()->setContextProperty("NativeBackend", &backend);
    engine.load(QUrl("qrc:/ui/qml/shell.qml"));
    if (engine.rootObjects().isEmpty()) return 4;
    QObject *root = engine.rootObjects().first();
    auto *window = root->findChild<QQuickWindow *>("mainWindow");
    if (!window) { qCritical() << "Main application window was not created"; return 5; }
    QObject::connect(&server, &QLocalServer::newConnection, &app, [&] {
        auto *socket = server.nextPendingConnection();
        if (socket) socket->deleteLater();
        window->show(); window->raise(); window->requestActivate();
    });
    if (smoke) {
        const QString output = args.value(smokeIndex + 1);
        if (output.isEmpty() || !QDir().mkpath(output)) return 6;
        auto *timer = new QTimer(&app);
        auto *step = new int(0);
        QObject::connect(timer, &QTimer::timeout, &app, [&, output, step] {
            const QStringList pages{"library", "fonts", "settings"};
            if (!root->property("ready").toBool() || root->property("failed").toBool()) {
                qCritical() << "UI did not become ready:" << root->property("message"); app.exit(8); return;
            }
            if (args.contains("--ui-regression") && *step < 2) {
                QVariant result;
                const char *method = *step == 0 ? "testPolling" : "testFonts";
                if (!QMetaObject::invokeMethod(root, method, Qt::DirectConnection, Q_RETURN_ARG(QVariant, result)) || !result.toBool()) {
                    qCritical() << "UI regression failed:" << method; app.exit(9); return;
                }
                std::cout << (*step == 0 ? "POLL_CONTENT_PRESERVED" : "FONT_POSITION_PRESERVED") << std::endl;
            }
            const auto image = window->grabWindow();
            if (image.isNull() || !image.save(QDir(output).filePath(pages.value(*step) + ".png"))) { app.exit(7); return; }
            ++*step;
            if (*step >= pages.size()) { delete step; app.quit(); return; }
            root->setProperty("page", pages[*step]);
        });
        timer->start(1200);
    }
    return app.exec();
}

#include "main.moc"
