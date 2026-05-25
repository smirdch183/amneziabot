# <p align="center">amneziabot</p>

## Web admin

Бот поднимает веб-панель вместе с polling. По умолчанию она доступна на `http://0.0.0.0:8080`.

Для запуска без веб-панели используйте параметр `-nogui`:

```bash
python bot.py -nogui
```

Добавьте `.env` рядом с `bot.py`:

```env
TOKEN=123456:telegram-token
ADMIN_ID=123456789
ADMIN_LOGIN=admin
ADMIN_PASS=change-me
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

В панели доступны пользователи, статусы подписок, редактирование доступа, продление дат, очистка, удаление, рассылка, скачивание бэкапа и переключение темы.

<p align="center">Телеграм бот для просмотр информации и доступом к амнезии (не интегрирована с амнезией).</p>
<p align="center"><i>Только в образовательных целях.</i></p>

## 📋 Функционал

- 🌐 Бот поднимает веб-панель вместе с polling. По умолчанию она доступна на `http://0.0.0.0:8080`.
- 👥 Управление пользователями (добавление, удаление, просмотр)
- 📅 Управление подписками (даты окончания)
- 🪧 Автоматические бэкапы базы данных
- 📦 В панели доступны пользователи, статусы подписок, редактирование доступа, продление дат, очистка, удаление, рассылка, скачивание бэкапа и переключение темы.

## Внимание!

### Все пути должны быть строго без пробелов и русского языка

### Для Windows должен быть установлен WSL (В поисковеке пишите wsl и устанавливаете его после перезагружаете пк)

## Как развернуть

### Установка

```bash
git clone https://github.com/smirdch183/amneziabot
cd ./amneziabot
```

### Python

Установка python3 linux
```bash
sudo apt install python3 python3-venv
```
[Установка Windows](https://www.python.org/downloads/)

Создание виртуального окружения Linux
```bash
python3 -m venv .venv
```

Создание виртуального окружения Windows
```bash
python -m venv .venv
```

### Настройка

Добавьте `.env` рядом с `bot.py`:

```env
TOKEN=123456:telegram-token
ADMIN_ID=123456789
ADMIN_LOGIN=admin
ADMIN_PASS=change-me
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

### Docker

Установка Docker
```bash
https://docs.docker.com/engine/install/
```

<!-- Настройка фала Dockerfile
```bash
nano Dockerfile
```

Вставляем
```bash
FROM python:3.14-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "bot.py"]
```
ctrl+x y Enter -->

Сборка бота
```bash
docker build -t amneziabot .
```

Запуск бота на Linux
```bash
docker run -d --env-file .env -p 8080:8080 -v $(pwd)/users.json:/app/users.json --name amneziabot amneziabot
```

Запуск бота на Windows PowerShell
```bash
docker run -d --env-file .env -p 8080:8080 -v ${pwd}/users.json:/app/users.json --name amneziabot amneziabot
```

### Docker Полезные команды
Остановить контейнер
```bash
docker stop amneziabot
```

Удалить контейнер
```bash
docker rm amneziabot
```

Просмотр в реальном времени бота
```bash
docker attach amneziabot
```

Запуск и просмотр сразу логов в python на Linux
```bash
docker run -d --env-file .env -p 8080:8080 -v $(pwd)/users.json:/app/users.json --name amneziabot amneziabot && docker attach amneziabot
```

Запуск и просмотр сразу логов в python на Windows PowerShell
```bash
docker run -d --env-file .env -p 8080:8080 -v ${pwd}/users.json:/app/users.json --name amneziabot amneziabot ; docker attach amneziabot
```

## Зависимости

- [aiogram](https://aiogram.dev)

## Отказ от ответственности

Данное хранилище предназначено только для образовательного и личного использования.
