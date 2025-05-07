import logging
import os
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import openai
import httpx

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурационные переменные - в реальном проекте должны быть вынесены в .env файл
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-webapp-url.com/kanban-app")

# Инициализация OpenAI API
openai.api_key = OPENAI_API_KEY

# Хранилище данных пользователей (в реальном приложении лучше использовать базу данных)
user_data = {}


class ProjectManager:
    """Класс для управления проектами и задачами"""

    @staticmethod
    async def generate_ai_response(user_id, message):
        """Генерирует ответ от ИИ на основе сообщения пользователя и контекста"""
        user_context = user_data.get(user_id, {}).get("context", [])

        # Создаем контекст с историей взаимодействия
        messages = [
            {"role": "system", "content": "Ты — ИИ-ассистент, который помогает вести проекты. "
                                         "Твоя задача — помогать с организацией задач, роадмапов и напоминать о статусах. "
                                         "Старайся задавать проактивные вопросы и быть инициативным. "
                                         "Отвечай кратко и по делу."}
        ]

        # Добавляем предыдущий контекст разговора
        for item in user_context[-5:]:  # Ограничиваем историю последними 5 сообщениями
            messages.append(item)

        # Добавляем текущее сообщение пользователя
        messages.append({"role": "user", "content": message})

        try:
            # Создаем HTTP клиент для работы с OpenAI API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-3.5-turbo",
                        "messages": messages,
                        "max_tokens": 500,
                        "temperature": 0.7,
                    },
                    timeout=30.0
                )

                if response.status_code == 200:
                    result = response.json()
                    ai_response = result["choices"][0]["message"]["content"]

                    # Обновляем контекст
                    user_context.append({"role": "user", "content": message})
                    user_context.append({"role": "assistant", "content": ai_response})

                    # Сохраняем обновленный контекст
                    if user_id not in user_data:
                        user_data[user_id] = {}
                    user_data[user_id]["context"] = user_context

                    return ai_response
                else:
                    logger.error(f"Ошибка OpenAI API: {response.text}")
                    return "Извините, произошла ошибка при обработке запроса. Попробуйте позже."
        except Exception as e:
            logger.error(f"Ошибка при обращении к OpenAI API: {e}")
            return "Извините, произошла ошибка при обработке запроса. Попробуйте позже."

    @staticmethod
    def get_projects(user_id):
        """Получить список проектов пользователя"""
        return user_data.get(user_id, {}).get("projects", [])

    @staticmethod
    def add_project(user_id, project_name, description=""):
        """Добавить новый проект"""
        if user_id not in user_data:
            user_data[user_id] = {"projects": [], "context": []}

        project_id = len(user_data[user_id]["projects"]) + 1

        new_project = {
            "id": project_id,
            "name": project_name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "tasks": [],
            "status": "В процессе"
        }

        user_data[user_id]["projects"].append(new_project)
        return new_project

    @staticmethod
    def get_project(user_id, project_id):
        """Получить проект по ID"""
        projects = ProjectManager.get_projects(user_id)
        for project in projects:
            if project["id"] == project_id:
                return project
        return None

    @staticmethod
    def add_task(user_id, project_id, task_name, description="", deadline=None):
        """Добавить новую задачу в проект"""
        project = ProjectManager.get_project(user_id, project_id)
        if not project:
            return None

        task_id = len(project["tasks"]) + 1

        new_task = {
            "id": task_id,
            "name": task_name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "deadline": deadline,
            "status": "Создана"
        }

        project["tasks"].append(new_task)
        return new_task

    @staticmethod
    def update_task_status(user_id, project_id, task_id, new_status):
        """Обновить статус задачи"""
        project = ProjectManager.get_project(user_id, project_id)
        if not project:
            return False

        for task in project["tasks"]:
            if task["id"] == task_id:
                task["status"] = new_status
                return True

        return False

    @staticmethod
    def update_task(user_id, project_id, task_id, task_data):
        """Обновить данные задачи"""
        project = ProjectManager.get_project(user_id, project_id)
        if not project:
            return False

        for task in project["tasks"]:
            if task["id"] == task_id:
                # Обновляем поля задачи
                if "name" in task_data:
                    task["name"] = task_data["name"]
                if "description" in task_data:
                    task["description"] = task_data["description"]
                if "status" in task_data:
                    task["status"] = task_data["status"]
                if "deadline" in task_data:
                    task["deadline"] = task_data["deadline"]
                return True

        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name

    # Инициализация данных пользователя
    if user_id not in user_data:
        user_data[user_id] = {"projects": [], "context": []}

    welcome_message = (
        f"Привет, {user_first_name}! Я ИИ-ассистент для управления проектами.\n\n"
        "Я могу помочь вам:\n"
        "• Создавать и управлять проектами\n"
        "• Вести канбан-доски для ваших задач\n"
        "• Отслеживать прогресс и напоминать о задачах\n\n"
        "Используйте следующие команды:\n"
        "/new_project - Создать новый проект\n"
        "/my_projects - Просмотреть ваши проекты\n"
        "/kanban - Открыть канбан-доску\n"
        "/help - Показать справку\n\n"
        "Или просто напишите мне, что вам нужно, и я помогу!"
    )

    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "Вот что я умею:\n\n"
        "Основные команды:\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n\n"
        "Управление проектами:\n"
        "/new_project - Создать новый проект\n"
        "/my_projects - Список ваших проектов\n"
        "/project {id} - Информация о проекте\n"
        "/kanban - Открыть канбан-доску\n\n"
        "Управление задачами:\n"
        "/add_task {project_id} {название} - Добавить задачу\n"
        "/tasks {project_id} - Показать задачи проекта\n"
        "/move_task {project_id} {task_id} {статус} - Изменить статус задачи\n\n"
        "Вы также можете просто написать мне, что вам нужно, "
        "и я постараюсь помочь!"
    )

    await update.message.reply_text(help_text)


async def new_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /new_project"""
    user_id = update.effective_user.id

    # Проверяем аргументы команды
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "Пожалуйста, укажите название проекта. Например:\n"
            "/new_project Мой новый сайт"
        )
        return

    project_name = " ".join(context.args)

    # Создаем проект
    new_project = ProjectManager.add_project(user_id, project_name)

    await update.message.reply_text(
        f"Проект '{new_project['name']}' успешно создан!\n"
        f"ID проекта: {new_project['id']}\n\n"
        "Теперь вы можете добавлять задачи в этот проект с помощью команды:\n"
        f"/add_task {new_project['id']} Название задачи"
    )

    # Создаем кнопки для быстрого доступа к функциям
    keyboard = [
        [
            InlineKeyboardButton("Добавить задачу", callback_data=f"add_task_{new_project['id']}"),
            InlineKeyboardButton("Открыть канбан", callback_data=f"open_kanban_{new_project['id']}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Проактивное предложение
    await update.message.reply_text(
        "Что хотите сделать дальше?",
        reply_markup=reply_markup
    )


async def my_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /my_projects"""
    user_id = update.effective_user.id
    projects = ProjectManager.get_projects(user_id)

    if not projects:
        await update.message.reply_text(
            "У вас еще нет проектов. Создайте первый проект с помощью команды:\n"
            "/new_project Название проекта"
        )
        return

    projects_text = "Ваши проекты:\n\n"

    for project in projects:
        total_tasks = len(project["tasks"])
        completed_tasks = sum(1 for task in project["tasks"] if task["status"] == "Завершена")

        projects_text += (
            f"📁 {project['name']} (ID: {project['id']})\n"
            f"Статус: {project['status']}\n"
            f"Задачи: {completed_tasks}/{total_tasks} завершено\n\n"
        )

    projects_text += (
        "Для просмотра задач проекта используйте команду:\n"
        "/tasks {project_id}"
    )

    # Создаем кнопки для быстрого доступа к канбан-доске
    keyboard = [
        [InlineKeyboardButton("Открыть канбан-доску", web_app=WebAppInfo(url=WEBAPP_URL))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        projects_text,
        reply_markup=reply_markup
    )


async def project_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /project {id}"""
    user_id = update.effective_user.id

    # Проверяем аргументы команды
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "Пожалуйста, укажите ID проекта. Например:\n"
            "/project 1"
        )
        return

    try:
        project_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID проекта должен быть числом.")
        return

    project = ProjectManager.get_project(user_id, project_id)

    if not project:
        await update.message.reply_text(
            f"Проект с ID {project_id} не найден. "
            "Проверьте список ваших проектов с помощью команды:\n"
            "/my_projects"
        )
        return

    total_tasks = len(project["tasks"])
    tasks_by_status = {}

    for task in project["tasks"]:
        status = task["status"]
        if status not in tasks_by_status:
            tasks_by_status[status] = 0
        tasks_by_status[status] += 1

    status_text = "\n".join(f"- {status}: {count}" for status, count in tasks_by_status.items())

    if not status_text:
        status_text = "- Нет задач"

    # Формируем информацию о проекте
    project_text = (
        f"📁 Проект: {project['name']} (ID: {project['id']})\n"
        f"Статус: {project['status']}\n"
        f"Создан: {datetime.fromisoformat(project['created_at']).strftime('%d.%m.%Y')}\n\n"
        f"Всего задач: {total_tasks}\n"
        f"Статусы задач:\n{status_text}\n\n"
        "Команды для управления проектом:\n"
        f"/tasks {project_id} - Просмотреть задачи проекта\n"
        f"/add_task {project_id} Название задачи - Добавить новую задачу"
    )

    # Создаем кнопки для быстрого доступа к функциям
    keyboard = [
        [
            InlineKeyboardButton("Добавить задачу", callback_data=f"add_task_{project_id}"),
            InlineKeyboardButton("Канбан проекта", web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}"))
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        project_text,
        reply_markup=reply_markup
    )


async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /add_task {project_id} {название}"""
    user_id = update.effective_user.id

    # Проверяем аргументы команды
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Пожалуйста, укажите ID проекта и название задачи. Например:\n"
            "/add_task 1 Разработать дизайн главной страницы"
        )
        return

    try:
        project_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID проекта должен быть числом.")
        return

    task_name = " ".join(context.args[1:])

    project = ProjectManager.get_project(user_id, project_id)

    if not project:
        await update.message.reply_text(
            f"Проект с ID {project_id} не найден. "
            "Проверьте список ваших проектов с помощью команды:\n"
            "/my_projects"
        )
        return

    # Создаем задачу
    new_task = ProjectManager.add_task(user_id, project_id, task_name)

    # Создаем клавиатуру для быстрого изменения статуса
    keyboard = [
        [
            InlineKeyboardButton("В работе", callback_data=f"task_{project_id}_{new_task['id']}_В работе"),
            InlineKeyboardButton("Завершена", callback_data=f"task_{project_id}_{new_task['id']}_Завершена")
        ],
        [
            InlineKeyboardButton("Открыть канбан", web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}"))
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Задача '{new_task['name']}' успешно добавлена в проект '{project['name']}'!\n"
        f"ID задачи: {new_task['id']}\n"
        f"Статус: {new_task['status']}\n\n"
        "Вы можете изменить статус задачи:",
        reply_markup=reply_markup
    )

    # Проактивное предложение
    await update.message.reply_text(
        "Хотите установить дедлайн для этой задачи? Если да, используйте команду:\n"
        f"/set_deadline {project_id} {new_task['id']} ДД.ММ.ГГГГ"
    )


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /tasks {project_id}"""
    user_id = update.effective_user.id

    # Проверяем аргументы команды
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "Пожалуйста, укажите ID проекта. Например:\n"
            "/tasks 1"
        )
        return

    try:
        project_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID проекта должен быть числом.")
        return

    project = ProjectManager.get_project(user_id, project_id)

    if not project:
        await update.message.reply_text(
            f"Проект с ID {project_id} не найден. "
            "Проверьте список ваших проектов с помощью команды:\n"
            "/my_projects"
        )
        return

    if not project["tasks"]:
        await update.message.reply_text(
            f"В проекте '{project['name']}' еще нет задач. "
            "Добавьте первую задачу с помощью команды:\n"
            f"/add_task {project_id} Название задачи"
        )
        return

    # Группируем задачи по статусам (простая канбан-доска)
    tasks_by_status = {}

    for task in project["tasks"]:
        status = task["status"]
        if status not in tasks_by_status:
            tasks_by_status[status] = []
        tasks_by_status[status].append(task)

    # Формируем текст с канбан-доской
    tasks_text = f"📋 Задачи проекта '{project['name']}':\n\n"

    for status, tasks_list in tasks_by_status.items():
        tasks_text += f"== {status} ==\n"
        for task in tasks_list:
            deadline_text = ""
            if task.get("deadline"):
                deadline_text = f" (до {task['deadline']})"

            tasks_text += f"• {task['name']} (ID: {task['id']}){deadline_text}\n"
        tasks_text += "\n"

    tasks_text += (
        "Для изменения статуса задачи используйте команду:\n"
        f"/move_task {project_id} [task_id] [новый статус]"
    )

    # Создаем кнопку для открытия канбан-доски
    keyboard = [
        [InlineKeyboardButton("Открыть канбан-доску", web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}"))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        tasks_text,
        reply_markup=reply_markup
    )


async def move_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /move_task {project_id} {task_id} {статус}"""
    user_id = update.effective_user.id

    # Проверяем аргументы команды
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "Пожалуйста, укажите ID проекта, ID задачи и новый статус. Например:\n"
            "/move_task 1 2 Завершена"
        )
        return

    try:
        project_id = int(context.args[0])
        task_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("ID проекта и ID задачи должны быть числами.")
        return

    new_status = " ".join(context.args[2:])

    # Обновляем статус задачи
    success = ProjectManager.update_task_status(user_id, project_id, task_id, new_status)

    if not success:
        await update.message.reply_text(
            "Не удалось обновить статус задачи. "
            "Проверьте ID проекта и ID задачи."
        )
        return

    await update.message.reply_text(
        f"Статус задачи успешно изменен на '{new_status}'."
    )

    # Проактивное напоминание
    project = ProjectManager.get_project(user_id, project_id)
    if new_status == "Завершена" and project:
        remaining_tasks = sum(1 for task in project["tasks"] if task["status"] != "Завершена")
        if remaining_tasks > 0:
            keyboard = [
                [InlineKeyboardButton("Открыть канбан-доску", web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}"))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"Отлично! В проекте '{project['name']}' осталось еще {remaining_tasks} незавершенных задач. "
                "Хотите просмотреть их на канбан-доске?",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"Поздравляю! Все задачи в проекте '{project['name']}' завершены! "
                "Хотите обновить статус проекта на 'Завершен'?"
            )


async def set_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /set_deadline {project_id} {task_id} {дата}"""
    user_id = update.effective_user.id

    # Проверяем аргументы команды
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "Пожалуйста, укажите ID проекта, ID задачи и дату дедлайна. Например:\n"
            "/set_deadline 1 2 31.12.2025"
        )
        return

    try:
        project_id = int(context.args[0])
        task_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("ID проекта и ID задачи должны быть числами.")
        return

    deadline = context.args[2]

    project = ProjectManager.get_project(user_id, project_id)

    if not project:
        await update.message.reply_text(
            f"Проект с ID {project_id} не найден."
        )
        return

    # Ищем задачу и устанавливаем дедлайн
    task_found = False
    for task in project["tasks"]:
        if task["id"] == task_id:
            task["deadline"] = deadline
            task_found = True
            break

    if not task_found:
        await update.message.reply_text(
            f"Задача с ID {task_id} не найдена в проекте."
        )
        return

    # Создаем кнопку для открытия канбан-доски
    keyboard = [
        [InlineKeyboardButton("Открыть канбан-доску", web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}"))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Дедлайн для задачи установлен на {deadline}.",
        reply_markup=reply_markup
    )


async def kanban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /kanban - открывает канбан-доску"""
    user_id = update.effective_user.id
    projects = ProjectManager.get_projects(user_id)

    if not projects:
        await update.message.reply_text(
            "У вас еще нет проектов. Создайте первый проект с помощью команды:\n"
            "/new_project Название проекта"
        )
        return

    # Если есть только один проект, открываем его канбан-доску
    if len(projects) == 1:
        project_id = projects[0]["id"]
        kanban_button = InlineKeyboardButton(
            text="Открыть канбан-доску",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}")
        )
        keyboard = InlineKeyboardMarkup([[kanban_button]])

        await update.message.reply_text(
            f"Нажмите на кнопку ниже, чтобы открыть канбан-доску для проекта '{projects[0]['name']}':",
            reply_markup=keyboard
        )
    else:
        # Если проектов несколько, предлагаем выбрать
        keyboard = []

        for project in projects:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{project['name']}",
                    web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project['id']}")
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Выберите проект, для которого хотите открыть канбан-доску:",
            reply_markup=reply_markup
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на inline кнопки"""
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")

    if len(data) >= 4 and data[0] == "task":
        # Обработка нажатия на кнопку изменения статуса задачи
        try:
            project_id = int(data[1])
            task_id = int(data[2])
            new_status = "_".join(data[3:])

            user_id = update.effective_user.id

            success = ProjectManager.update_task_status(user_id, project_id, task_id, new_status)

            if success:
                await query.edit_message_text(
                    text=f"Статус задачи успешно изменен на '{new_status}'."
                )

                # Отправляем проактивное сообщение
                project = ProjectManager.get_project(user_id, project_id)
                if new_status == "Завершена" and project:
                    remaining_tasks = sum(1 for task in project["tasks"] if task["status"] != "Завершена")
                    if remaining_tasks > 0:
                        keyboard = [
                            [InlineKeyboardButton("Открыть канбан-доску", web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}"))]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)

                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"Отлично! В проекте '{project['name']}' осталось еще {remaining_tasks} незавершенных задач.",
                            reply_markup=reply_markup
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"Поздравляю! Все задачи в проекте '{project['name']}' завершены!"
                        )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Не удалось обновить статус задачи."
                )
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при обработке запроса."
            )
    elif len(data) >= 2 and data[0] == "add_task":
        # Обработка нажатия на кнопку добавления задачи
        try:
            project_id = int(data[1])

            # Отправляем инструкцию по добавлению задачи
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Чтобы добавить задачу в проект, используйте команду:\n/add_task {project_id} Название задачи"
            )
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при обработке запроса."
            )
    elif len(data) >= 2 and data[0] == "open_kanban":
        # Обработка нажатия на кнопку открытия канбан-доски
        try:
            project_id = int(data[1])

            # Создаем кнопку для открытия канбан-доски
            keyboard = [
                [InlineKeyboardButton("Открыть канбан-доску", web_app=WebAppInfo(url=f"{WEBAPP_URL}?project_id={project_id}"))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Нажмите на кнопку ниже, чтобы открыть канбан-доску:",
                reply_markup=reply_markup
            )
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при обработке запроса."
            )


async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик обычных сообщений"""
    user_id = update.effective_user.id
    message_text = update.message.text

    # Генерируем ответ от ИИ
    ai_response = await ProjectManager.generate_ai_response(user_id, message_text)

    # Анализируем ответ ИИ для выявления потенциальных действий
    if "создать проект" in ai_response.lower():
        # Добавляем подсказку о команде создания проекта
        ai_response += "\n\nВы можете создать новый проект с помощью команды:\n/new_project Название проекта"

    elif "добавить задачу" in ai_response.lower() or "создать задачу" in ai_response.lower():
        # Добавляем подсказку о команде создания задачи
        projects = ProjectManager.get_projects(user_id)
        if projects:
            project_id = projects[0]["id"]
            ai_response += f"\n\nВы можете добавить задачу с помощью команды:\n/add_task {project_id} Название задачи"
        else:
            ai_response += "\n\nСначала создайте проект с помощью команды:\n/new_project Название проекта"

    elif "канбан" in ai_response.lower() or "доск" in ai_response.lower():
        # Добавляем подсказку о канбан-доске
        ai_response += "\n\nВы можете открыть канбан-доску с помощью команды:\n/kanban"

    await update.message.reply_text(ai_response)


async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик данных из мини-приложения"""
    # Проверяем, что пришли данные из веб-приложения
    if not update.effective_message.web_app_data:
        return

    user_id = update.effective_user.id

    try:
        # Парсим данные JSON из веб-приложения
        data = json.loads(update.effective_message.web_app_data.data)

        # Выводим полученные данные в лог для отладки
        logger.info(f"Получены данные из веб-приложения: {data}")

        # Обрабатываем различные типы данных из приложения
        if data.get("action") == "statusUpdate":
            # Обновляем статус задачи в базе данных
            if ProjectManager.update_task_status(
                user_id,
                int(data["projectId"]),
                int(data["id"]),
                data["status"]
            ):
                await update.message.reply_text(
                    f"Статус задачи обновлен на '{data['status']}'."
                )
            else:
                await update.message.reply_text(
                    "Не удалось обновить статус задачи."
                )
        elif data.get("id") and data.get("name"):
            # Обновляем существующую задачу
            if ProjectManager.update_task(
                user_id,
                int(data["projectId"]),
                int(data["id"]),
                {
                    "name": data["name"],
                    "description": data.get("description", ""),
                    "status": data.get("status", "В работе"),
                    "deadline": data.get("deadline")
                }
            ):
                await update.message.reply_text(
                    f"Задача '{data['name']}' обновлена."
                )
            else:
                await update.message.reply_text(
                    "Не удалось обновить задачу."
                )
        elif data.get("name"):
            # Создаем новую задачу
            new_task = ProjectManager.add_task(
                user_id,
                int(data["projectId"]),
                data["name"],
                data.get("description", ""),
                data.get("deadline")
            )

            if new_task:
                await update.message.reply_text(
                    f"Задача '{data['name']}' создана."
                )
            else:
                await update.message.reply_text(
                    "Не удалось создать задачу."
                )
    except Exception as e:
        logger.error(f"Ошибка при обработке данных из веб-приложения: {e}")
        await update.message.reply_text(
            "Произошла ошибка при обработке данных из канбан-доски."
        )


def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new_project", new_project))
    application.add_handler(CommandHandler("my_projects", my_projects))
    application.add_handler(CommandHandler("project", project_info))
    application.add_handler(CommandHandler("add_task", add_task))
    application.add_handler(CommandHandler("tasks", tasks))
    application.add_handler(CommandHandler("move_task", move_task))
    application.add_handler(CommandHandler("set_deadline", set_deadline))
    application.add_handler(CommandHandler("kanban", kanban_command))

    # Обработчик нажатий на кнопки
    application.add_handler(CallbackQueryHandler(button_handler))

    # Обработчик данных из веб-приложения
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))

    # Обработчик обычных сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))

    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
