import os
import json
import httpx
from parser import is_url, parse_vacancy, text_to_vacancy

ANTHROPIC_API_URL = "https://api.proxyapi.ru/anthropic/v1/messages"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ─── Методика: 18 красных флагов ────────────────────────────────────────────

RED_FLAGS_METHODOLOGY = """
## МЕТОДИКА ОЦЕНКИ ВАКАНСИИ — 18 КРАСНЫХ ФЛАГОВ

### ГРУППА 1: ДЕНЬГИ И УСЛОВИЯ (вес: высокий)
1. СВЕРХЗАРПЛАТА — зарплата значительно выше рынка при размытых или минимальных требованиях (без опыта 150к+, курьер 200к и т.п.)
2. ПЛАТНЫЙ ВХОД — требование залога, покупки формы/оборудования/обучения за свой счёт ДО начала работы
3. РАЗМЫТАЯ ОПЛАТА — «договорная», «обсудим на собеседовании», полное отсутствие вилки при высоких обещаниях в тексте
4. ПРОЦЕНТ БЕЗ ОКЛАДА — только %, только комиссия, никакого фикса — классика сетевого маркетинга

### ГРУППА 2: КОМПАНИЯ И КОНТАКТЫ (вес: высокий)
5. АНОНИМНЫЙ РАБОТОДАТЕЛЬ — нет названия компании, только «крупная компания», «наш клиент», «успешный бизнес»
6. НЕТ АДРЕСА — нет физического адреса офиса или он размытый («центр города», «метро Х»)
7. ЛИЧНЫЕ КОНТАКТЫ — связь только через личный WhatsApp/Telegram, без корпоративной почты или официального сайта
8. ПОДОЗРИТЕЛЬНЫЙ ДОМЕН — почта на бесплатном домене (gmail, mail.ru, yandex) для найма в «крупную компанию»

### ГРУППА 3: ТЕКСТ И СТИЛЬ ВАКАНСИИ (вес: средний)
9. ШАБЛОННЫЙ ТЕКСТ — одинаковые фразы «мы динамично развивающаяся компания», «дружный коллектив», «карьерный рост» без конкретики
10. СРОЧНОСТЬ — «требуются СЕГОДНЯ», «осталось 2 места», «только до конца недели» — создание искусственного дефицита
11. ЗАВЫШЕННЫЕ ОБЕЩАНИЯ — гарантии карьерного роста, пассивный доход, «работа мечты», «изменим твою жизнь»
12. РАЗМЫТЫЕ ОБЯЗАННОСТИ — нет конкретных задач, только «общение с клиентами», «помощь руководителю», «развитие бизнеса»

### ГРУППА 4: СХЕМЫ И ФОРМАТЫ (вес: высокий)
13. СЕТЕВОЙ МАРКЕТИНГ — упоминание «партнёров», «структуры», «приглашения друзей», слова «МЛМ», «многоуровневый»
14. ФИНАНСОВЫЕ СХЕМЫ — работа с деньгами/счетами физлиц, «финансовый посредник», переводы, криптовалюта
15. УДАЛЁННАЯ РАБОТА БЕЗ ОПЫТА С ВЫСОКОЙ ЗАРПЛАТОЙ — удалёнка + без опыта + 100к+ без объяснений
16. ДРОПШИППИНГ / ЗАКУПКИ — «помогать с закупками», «принимать посылки», «перепродажа товаров» с предоплатой

### ГРУППА 5: ПРОЦЕСС НАЙМА (вес: средний)
17. БЫСТРЫЙ НАЙМ БЕЗ ПРОВЕРОК — «берём всех», «без резюме», «собеседование 5 минут», «начать можно завтра»
18. НЕФОРМАЛЬНЫЙ ПРОЦЕСС — оформление «потом», «договоримся», работа без трудового договора, ИП/самозанятость навязывается
"""

# ─── Системный промпт для анализа ───────────────────────────────────────────

SYSTEM_PROMPT = f"""Ты — эксперт по безопасности на рынке труда в России. Твоя задача — анализировать вакансии и определять, является ли работодатель мошенником или недобросовестным нанимателем.

{RED_FLAGS_METHODOLOGY}

## ИНСТРУКЦИЯ ПО АНАЛИЗУ

Тебе передаётся информация о вакансии. Ты должен:

1. **Проверить текст вакансии** на все 18 красных флагов
2. **Найти информацию о работодателе** в интернете:
   - Поискать отзывы на DreamJob, Otzovik, правдасотрудников
   - Поискать «[название компании] мошенники», «[название компании] развод», «[название компании] отзывы сотрудников»
   - Проверить наличие компании (если есть ИНН или название — поискать на rusprofile.ru)
3. **Сформировать вердикт**

## ФОРМАТ ОТВЕТА

Отвечай ТОЛЬКО валидным JSON без markdown-обёртки. Структура:

{{
  "verdict": "МОШЕННИК" | "ПОДОЗРИТЕЛЬНО" | "НОРМ" | "НЕДОСТАТОЧНО ДАННЫХ",
  "score": <число от 0 до 100, где 100 = точно мошенник>,
  "summary": "<2-3 предложения — главный вывод>",
  "red_flags": [
    {{
      "flag": "<название флага из методики>",
      "severity": "высокий" | "средний" | "низкий",
      "description": "<что конкретно нашёл в этой вакансии>"
    }}
  ],
  "green_flags": ["<хорошие признаки, если есть>"],
  "employer_research": {{
    "found": true | false,
    "reviews_summary": "<что нашёл об отзывах сотрудников>",
    "legal_info": "<что нашёл о юридическом статусе компании>",
    "sources": ["<ссылки на источники>"]
  }},
  "recommendation": "<конкретный совет пользователю — что делать дальше>"
}}

Будь конкретным и честным. Если данных мало — скажи это. Не выдумывай информацию о компании.
КРИТИЧЕСКИ ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до или после JSON. Никаких объяснений. Только JSON объект начиная с {{ и заканчивая }}.
"""


async def call_claude_with_search(vacancy_data: dict) -> dict:
    """Вызываем Claude с web_search инструментом"""

    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY не установлен. Добавьте его в переменные окружения.")

    # Формируем сообщение пользователя
    parts = []

    if vacancy_data.get("title"):
        parts.append(f"**Должность:** {vacancy_data['title']}")
    if vacancy_data.get("employer"):
        parts.append(f"**Работодатель:** {vacancy_data['employer']}")
    if vacancy_data.get("salary"):
        parts.append(f"**Зарплата:** {vacancy_data['salary']}")
    if vacancy_data.get("experience"):
        parts.append(f"**Опыт:** {vacancy_data['experience']}")
    if vacancy_data.get("address"):
        parts.append(f"**Адрес:** {vacancy_data['address']}")
    if vacancy_data.get("url"):
        parts.append(f"**Ссылка:** {vacancy_data['url']}")
    if vacancy_data.get("employer_trusted") is True:
        parts.append("**HH.ru:** работодатель имеет статус «проверенный»")

    parts.append(f"\n**Текст вакансии:**\n{vacancy_data['description']}")

    user_message = "\n".join(parts)

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4000,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_message}
        ],
    }

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(ANTHROPIC_API_URL, json=payload, headers=headers)

    if resp.status_code != 200:
        error_body = resp.text
        raise ValueError(f"Claude API ошибка {resp.status_code}: {error_body}")

    data = resp.json()

    # Извлекаем финальный текстовый ответ
    raw_text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            raw_text = block.get("text", "")

    if not raw_text:
        raise ValueError("Claude не вернул текстовый ответ")

    # Парсим JSON
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[-1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        # Попытка найти JSON внутри текста
        import re
        json_match = re.search(r'\{[\s\S]*\}', raw_text)
        if json_match:
            result = json.loads(json_match.group())
        else:
            raise ValueError(f"Не удалось распарсить JSON ответ Claude: {e}\n\nОтвет: {raw_text[:500]}")

    return result


async def analyze_vacancy(user_input: str) -> dict:
    """Главная функция анализа — принимает URL или текст"""

    # Определяем что пришло
    if is_url(user_input):
        try:
            vacancy_data = await parse_vacancy(user_input)
        except Exception as e:
            # Если не смогли спарсить — отдаём ошибку с объяснением
            return {
                "verdict": "ОШИБКА",
                "score": 0,
                "summary": f"Не удалось получить данные по ссылке: {str(e)}",
                "red_flags": [],
                "green_flags": [],
                "employer_research": {"found": False, "reviews_summary": "", "legal_info": "", "sources": []},
                "recommendation": "Попробуйте скопировать текст вакансии и вставить его вручную.",
                "parsed": False,
            }
    else:
        vacancy_data = text_to_vacancy(user_input)

    # Анализируем
    result = await call_claude_with_search(vacancy_data)

    # Добавляем мета-информацию
    result["meta"] = {
        "source": vacancy_data.get("source", "text"),
        "title": vacancy_data.get("title", ""),
        "employer": vacancy_data.get("employer", ""),
        "salary": vacancy_data.get("salary", ""),
        "url": vacancy_data.get("url", ""),
    }

    return result
