# <p align="center">amneziabot</p>

<p align="center">Телеграм бот для просмотр информации и доступом к амнезии (не интегрирована с амнезией).</p>
<p align="center"><i>Только в образовательных целях.</i></p>

## 📋 Функционал

- 👥 Управление пользователями (добавление, удаление, просмотр)
- 📅 Управление подписками (даты окончания)
- 📦 Автоматические бэкапы базы данных

## Как развернуть

### Установка

```bash
git clone https://github.com/smirdch183/amneziabot
cd ./amneziabot
```

### Python

Установка python3
```bash
sudo apt install python3 python3-venv
```

Создание виртуального окружения
```bash
python3 -m venv .venv
```

### Настройка

Откройте файл config.py и замените на свои данные

Linux
```bash
nano config.py
```

### Docker

Установка Docker
```bash
https://docs.docker.com/engine/install/
```

Настройка фала Dockerfile
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
ctrl+x y Enter

```bash
docker build -t amneziabot .
docker run -d -v $(pwd)/users.json:/app/users.json --name amneziabot amneziabot
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

Запуск и просмотр сразу логов в python
```bash
docker run -d -v $(pwd)/users.json:/app/users.json --name amneziabot amneziabot && docker attach amneziabot
```

## Dependencies

- [aiogram](https://github.com/eternnoir/pyTelegramBotAPI/)
- [zoneinfo](https://pypi.org/project/python-dotenv/)

## Отказ от ответственности

Данное хранилище предназначено только для образовательного и личного использования.