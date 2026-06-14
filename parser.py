import os
import re
import httpx
from bs4 import BeautifulSoup


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def detect_source(url: str) -> str:
    if "hh.ru" in url:
        return "hh"
    elif "avito.ru" in url:
        return "avito"
    elif "trudvsem.ru" in url:
        return "trudvsem"
    return "unknown"


async def parse_hh(url: str) -> dict:
    """Парсим вакансию с HH.ru через их публичный API"""
    # Извлекаем vacancy ID из URL
    match = re.search(r"/vacancy/(\d+)", url)
    if not match:
        raise ValueError("Не удалось извлечь ID вакансии из ссылки HH.ru")

    vacancy_id = match.group(1)
    api_url = f"https://api.hh.ru/vacancies/{vacancy_id}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "HH-User-Agent": "JobChecker/1.0 (alena@gmail.com)",
        "Authorization": f"Bearer {os.environ.get('HH_TOKEN', '')}",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(api_url, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"HH API вернул {resp.status_code}")
        data = resp.json()

    # Извлекаем нужные поля
    salary = data.get("salary")
    salary_str = ""
    if salary:
        frm = salary.get("from")
        to = salary.get("to")
        currency = salary.get("currency", "RUR")
        if frm and to:
            salary_str = f"{frm}–{to} {currency}"
        elif frm:
            salary_str = f"от {frm} {currency}"
        elif to:
            salary_str = f"до {to} {currency}"

    employer = data.get("employer", {})
    employer_name = employer.get("name", "")
    employer_url = employer.get("alternate_url", "")
    employer_trusted = employer.get("trusted", False)

    description_html = data.get("description", "")
    soup = BeautifulSoup(description_html, "html.parser")
    description_text = soup.get_text(separator="\n", strip=True)

    # Собираем опыт
    experience = data.get("experience", {}).get("name", "")

    # Адрес
    address = data.get("address")
    address_str = ""
    if address:
        address_str = address.get("raw", "")

    return {
        "source": "hh",
        "title": data.get("name", ""),
        "employer": employer_name,
        "employer_url": employer_url,
        "employer_trusted": employer_trusted,
        "salary": salary_str,
        "experience": experience,
        "address": address_str,
        "description": description_text[:4000],
        "url": url,
        "employer_id": str(employer.get("id", "")),
    }


async def parse_avito(url: str) -> dict:
    """Парсим вакансию с Авито через HTTP + BeautifulSoup"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers=headers,
    ) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise ValueError(f"Авито вернул {resp.status_code}. Возможно, заблокирован доступ — попробуйте вставить текст вакансии вручную.")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Заголовок
    title_tag = soup.find("h1", {"data-marker": "item-view/title-info"})
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Работодатель
    employer_tag = soup.find("div", {"data-marker": "seller-info/name"})
    if not employer_tag:
        employer_tag = soup.find("a", {"data-marker": "seller-info/name"})
    employer = employer_tag.get_text(strip=True) if employer_tag else ""

    # Зарплата
    salary_tag = soup.find("span", {"data-marker": "item-view/item-price"})
    salary = salary_tag.get_text(strip=True) if salary_tag else ""

    # Описание
    desc_tag = soup.find("div", {"data-marker": "item-view/item-description"})
    description = desc_tag.get_text(separator="\n", strip=True) if desc_tag else ""

    # Адрес
    address_tag = soup.find("span", {"data-marker": "delivery-location-redesign/location"})
    if not address_tag:
        address_tag = soup.find("div", class_=lambda c: c and "location" in c.lower())
    address = address_tag.get_text(strip=True) if address_tag else ""

    if not title and not description:
        raise ValueError("Не удалось извлечь данные с Авито. Сайт мог заблокировать запрос — попробуйте вставить текст вакансии вручную.")

    return {
        "source": "avito",
        "title": title,
        "employer": employer,
        "employer_url": url,
        "employer_trusted": False,
        "salary": salary,
        "experience": "",
        "address": address,
        "description": description[:4000],
        "url": url,
        "employer_id": "",
    }


async def parse_trudvsem(url: str) -> dict:
    """Парсим вакансию с trudvsem.ru через API, с fallback на поиск"""

    match = re.search(r"/vacancy/card/(\d+)/([a-f0-9\-]+)", url)
    if not match:
        raise ValueError("Не удалось извлечь ID вакансии из ссылки trudvsem.ru")

    company_code = match.group(1)
    vacancy_id = match.group(2)

    # Пробуем прямой запрос к вакансии
    api_url = f"https://opendata.trudvsem.ru/api/v1/vacancies/vacancy/{company_code}/{vacancy_id}"

    title = ""
    employer_name = ""
    salary = ""
    experience = ""
    address = ""
    description = ""
    inn = ""

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(api_url)
        if resp.status_code == 200:
            data = resp.json()
            vacancy = data.get("results", {}).get("vacancy", {})

            if vacancy:
                salary_min = vacancy.get("salary_min", "")
                salary_max = vacancy.get("salary_max", "")
                if salary_min and salary_max:
                    salary = f"{salary_min}–{salary_max} руб."
                elif salary_min:
                    salary = f"от {salary_min} руб."
                elif salary_max:
                    salary = f"до {salary_max} руб."
                else:
                    salary = str(vacancy.get("salary", ""))

                company = vacancy.get("company", {})
                employer_name = company.get("name", "")
                inn = company.get("inn", "")
                title = vacancy.get("job-name", "")
                experience = vacancy.get("requirement", {}).get("experience", "")
                address = vacancy.get("location", {}).get("location", "")
                description = vacancy.get("duty", "")

    # Если API не дал описание — ищем вакансию через поиск по API
    if not description:
        try:
            search_url = f"https://opendata.trudvsem.ru/api/v1/vacancies?limit=1&offset=0&region={company_code}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(search_url)
                if resp.status_code == 200:
                    data = resp.json()
                    vacancies = data.get("results", {}).get("vacancies", [])
                    for v in vacancies:
                        vac = v.get("vacancy", {})
                        if vac.get("id", "") == vacancy_id or vac.get("job-name", ""):
                            description = vac.get("duty", "")
                            if not title:
                                title = vac.get("job-name", "")
                            break
        except Exception:
            pass

    # Если всё ещё нет описания — собираем из полей то что есть
    if not description and title:
        parts = []
        if title:
            parts.append(f"Должность: {title}")
        if employer_name:
            parts.append(f"Работодатель: {employer_name}")
        if salary:
            parts.append(f"Зарплата: {salary}")
        if experience:
            parts.append(f"Опыт: {experience}")
        if address:
            parts.append(f"Адрес: {address}")
        parts.append(f"Источник: Работа России (trudvsem.ru)")
        parts.append(f"Ссылка: {url}")
        description = "\n".join(parts)

    if not title and not description:
        raise ValueError(
            "Не удалось получить данные с trudvsem.ru. "
            "Пожалуйста, откройте вакансию в браузере, скопируйте весь текст и вставьте его в поле анализа."
        )

    return {
        "source": "trudvsem",
        "title": title,
        "employer": employer_name,
        "employer_url": url,
        "employer_trusted": False,
        "salary": salary,
        "experience": experience,
        "address": address,
        "description": description[:4000],
        "url": url,
        "employer_id": inn,
    }
async def parse_vacancy(url: str) -> dict:
    source = detect_source(url)
    if source == "hh":
        return await parse_hh(url)
    elif source == "avito":
        return await parse_avito(url)
    elif source == "trudvsem":
        return await parse_trudvsem(url)
    else:
        raise ValueError("Поддерживаются только ссылки с hh.ru, avito.ru и trudvsem.ru")


def text_to_vacancy(text: str) -> dict:
    """Если пользователь вставил текст — оборачиваем в структуру"""
    return {
        "source": "text",
        "title": "",
        "employer": "",
        "employer_url": "",
        "employer_trusted": False,
        "salary": "",
        "experience": "",
        "address": "",
        "description": text[:5000],
        "url": "",
        "employer_id": "",
    }
