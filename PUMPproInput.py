from requests import post
from pybit.unified_trading import HTTP
from datetime import datetime
from time import sleep
import json
import os
import logging
from dotenv import load_dotenv

load_dotenv()
"""Создает необходимые папки"""
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

# Конфигурация из .env
TGBOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "355166419")
PRICE_THRESHOLD = float(input("Введите процент движения цены: "))
CHECK_INTERVAL = int(input("Введите интервал проверки в секундах: "))
try:
    TIMEFRAME = [
        int(input("Введите требуемый период изменения цены в минутах: ")) * 60 * 1000
        for _ in range(int(input("Количество временных периодов: ")))
    ]
except Exception:
    print("Ошибка ввода данных, временнной интервал будет задан по умолчанию (10min)")
    TIMEFRAME = [10 * 60 * 1000]
if not TGBOT:
    logger.error("TELEGRAM_BOT_TOKEN не найден в .env файле!")
    exit(1)
REPORT_INTERVAL = int(input("Введите интервал отчета по сигналам в минутах: "))
TG_API_URL = "http://api.telegram.org/bot"
session = HTTP()


def send_message(msg="Text message", chat_id=CHAT_ID):
    try:
        url = f"{TG_API_URL}{TGBOT}/sendMessage"
        params = {"chat_id": chat_id, "text": msg}
        response = post(url, params=params)
        logger.info(f"Сообщение отправлено: {msg}")
        return response
    except Exception as e:
        logging.error(f"Ошибка отправки в Telegram: {e}")
        return None


def time_formatter(unix=1731196800000):
    # функция для конвертации време� uniх-формата
    # Принимает 1 аргумент
    # Отдает отформатированную для человека функцию
    timestamp = unix / 1000  # converting UNIX to timestamp
    dt_object = datetime.fromtimestamp(timestamp)
    return dt_object


def get_all_symbols_names():
    logger.info("Получаем топ символов по объему")
    try:
        response = session.get_tickers(category="spot", limit=1000)
        if response["retCode"] != 0:
            logger.error(f"Ошибка API: {response['retMsg']}")
            return []

        only_names = [
            t for t in response["result"]["list"] if t["symbol"].endswith("USDT")
        ]
        sorted_pairs = sorted(
            only_names, key=lambda x: float(x["turnover24h"]), reverse=True
        )[:100]
        result = [pair["symbol"] for pair in sorted_pairs]
        logger.info(f"Найдено {len(result)} символов")
        return result
    except Exception as e:
        logger.error(f"Ошибка получения символов: {e}")
        return []


def check_signal_by_symbol(symbol="BTCUSDT"):
    try:
        ticker = session.get_tickers(category="spot", symbol=symbol)
        if ticker["retCode"] == 0 and ticker["result"]["list"]:
            cur_price = float(ticker["result"]["list"][0]["lastPrice"])
            return cur_price
        return None
    except Exception as e:
        logger.error(f"Ошибка получения цены для {symbol}: {e}")
        return None


def run():
    data_file = "data/ticker_data.json"
    signals_bull_count = 0
    signals_bear_count = 0
    cur_time_for_report = datetime.now().timestamp()
    while True:
        try:
            if os.path.exists(data_file):
                with open(data_file, "r", encoding="utf-8") as file:
                    data = json.load(file)
            else:
                data = {}
            all_symbols = get_all_symbols_names()
            if not all_symbols:
                logger.warning("Не удалось получить символы, ждем 60 секунд")
                sleep(60)
                continue
            cur_time = datetime.now().timestamp()
            signals_count = 0
            if cur_time_for_report + (REPORT_INTERVAL * 60 * 1000) < cur_time:
                msg_report = f"За последние {REPORT_INTERVAL} минут: БЫЧЬИХ сигналов {signals_bull_count} | МЕДВЕЖЬИХ мигналов {signals_bear_count}"
                send_message(msg_report)
                logger.info(f"Отчет: {msg_report}")
                signals_bear_count = 0
                signals_bull_count = 0
                cur_time_for_report = cur_time_for_report + (
                    REPORT_INTERVAL * 60 * 1000
                )
            for symbol in all_symbols:
                cur_price = check_signal_by_symbol(symbol)
                if cur_price is None:
                    continue
                if symbol not in data:
                    data[symbol] = {}
                for time in TIMEFRAME:
                    pres_time = "window_" + str(time) + "min"
                    if pres_time not in data[symbol]:
                        data[symbol][pres_time] = []
                    data[symbol][pres_time].append(
                        {"price": cur_price, "time": cur_time}
                    )
                    data[symbol][pres_time] = [
                        item
                        for item in data[symbol][pres_time]
                        if cur_time - item["time"] <= time / 1000
                    ]
                    if len(data[symbol][pres_time]) >= 2:
                        oldest_price = data[symbol][pres_time][0]["price"]
                        price_change = ((cur_price - oldest_price) / oldest_price) * 100
                        if abs(price_change) >= PRICE_THRESHOLD:
                            direction = "рост" if price_change > 0 else "падение"
                            msg = f"{symbol} {direction} на {abs(price_change):.2f}% за {time/60000:.0f} мин"
                            send_message(msg)
                            signals_count += 1
                            if direction == "рост":
                                signals_bull_count += 1
                            elif direction == "падение":
                                signals_bear_count += 1
                            logger.info(f"Сигнал: {msg}")
                    sleep(0.1)  # Пауза между запросами
                    if len(data[symbol][pres_time]) >= 4:
                        past3ago_price = data[symbol][pres_time][-3]["price"]
                        price_change_fast = (
                            (cur_price - past3ago_price) / past3ago_price
                        ) * 100
                        if abs(price_change_fast) >= PRICE_THRESHOLD:
                            direction_fast = (
                                "ВБРОС!!!" if price_change_fast > 0 else "ОБВАЛ!!!"
                            )
                            msg_fall = f"{symbol} {direction_fast} на {abs(price_change_fast):.2f}% за {CHECK_INTERVAL*3:.0f} сек"
                            send_message(msg_fall)
                            signals_count += 1
                            if direction_fast == "ВБРОС!!!":
                                signals_bull_count += 1
                            elif direction_fast == "ОБВАЛ!!!":
                                signals_bear_count += 1
                            logger.info(f"Сигнал: {msg_fall}")
            with open(data_file, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            logger.info(
                f"Цикл завершен. Сигналов: {signals_count}. Ждем {CHECK_INTERVAL} сек."
            )
            sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Остановлено пользователем")
            break
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            sleep(30)


if __name__ == "__main__":
    print("=" * 50)
    print("Crypto Signal Bot")
    print("=" * 50)
    print(f"Порог сигнала: {PRICE_THRESHOLD}%")
    print(f"Интервал проверки: {CHECK_INTERVAL} сек")
    for time in TIMEFRAME:
        print(f"Таймфрейм: {time/60000:.0f} мин")
    print("=" * 50)
    print(f"Интервал отчета по сигналам: {REPORT_INTERVAL} мин")

    try:
        run()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        input("Нажмите Enter для выхода...")
