# Sideshelf

Личный магазин iOS-приложений. Одна команда собирает текущий Xcode-проект в `.ipa` с development-подписью
и выкладывает страницу установки по воздуху (`itms-services`) на `https://<mac>.<tailnet>.ts.net/<app>/`
через `tailscale serve`. Страница видна только устройствам в tailnet. С флагом `--push` сборка ещё и сама
ставится и запускается на iPhone через `devicectl`, если Mac его видит (кабель или та же Wi-Fi).

## Устройство

- `skill/` — Claude Code скилл `sideshelf` (подключён симлинком `~/.claude/skills/sideshelf → skill/`).
  - `SKILL.md` — как и когда запускать, разбор проблем.
  - `scripts/ota-deploy.sh` — весь пайплайн: archive → export → manifest + страница → локальный
    `python3 -m http.server 8473` → `tailscale serve --bg 8473` → (`--push`) `devicectl install/launch`.
- `examples/TailDrop/` — демо-приложение (XcodeGen: `xcodegen generate`).
- Данные раздачи: `~/.sideshelf/www/<app>/`, лог сервера `~/.sideshelf/http.log`.

## Запуск

Из папки с `.xcodeproj` / `.xcworkspace`:

```
~/.claude/skills/sideshelf/scripts/ota-deploy.sh [--scheme NAME] [--push]
```

## Ограничения

Development-подпись: только устройства из профиля аккаунта (до 100 iPhone в год), профиль живёт ~год.
Нет автообновлений. Mac должен быть включён. Tailscale из App Store на macOS не умеет раздавать папки,
поэтому файлы отдаёт локальный сервер, а Tailscale только проксирует.

## Идеи

Иконки приложений на странице, история версий и откат, уведомление о новой сборке.
