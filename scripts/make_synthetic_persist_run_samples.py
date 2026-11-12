#!/usr/bin/env python3
"""Синтетические S1/S2 для smoke записи прогона. Без клиентских данных.

Пишет var/<window-id>/synthetic/S1_synthetic.txt и S2_synthetic.xls.
Это проверка записи и прав, не сверка реальных выгрузок.
Решение 2026-10-27: клиентские образцы не класть на стенд и не коммитить.
"""

from __future__ import annotations

import argparse
import calendar
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWN_ACCOUNT = "40702810000000000001"
OTHER_ACCOUNT = "40702810000000000002"
AMOUNT = "100.00"
PAYER = "Synthetic payer"
PURPOSE = "synthetic smoke"


def _record(code: int, payload: bytes) -> bytes:
    return struct.pack("<HH", code, len(payload)) + payload


def _bof(kind: int) -> bytes:
    payload = struct.pack("<HHHHII", 0x0600, kind, 0x0DBB, 1996, 0x00C9, 0x0106)
    return _record(0x0809, payload)


def _utf16_label(row: int, col: int, text: str) -> bytes:
    encoded = text.encode("utf-16-le")
    payload = struct.pack("<HHH", row, col, 0)
    payload += struct.pack("<HB", len(text), 1) + encoded
    return _record(0x0204, payload)


def _workbook_stream(rows: list[list[tuple[int, str]]]) -> bytes:
    labels = bytearray()
    max_col = 0
    for row_index, cells in enumerate(rows):
        for col, text in cells:
            labels += _utf16_label(row_index, col, text)
            max_col = max(max_col, col + 1)
    dimensions = struct.pack("<IIHHH", 0, len(rows), 0, max_col, 0)
    sheet = bytearray()
    sheet += _bof(0x0010)
    sheet += _record(0x0200, dimensions)
    sheet += labels
    sheet += _record(0x000A, b"")
    globals_head = bytearray()
    globals_head += _bof(0x0005)
    globals_head += _record(0x0042, struct.pack("<H", 0x04B0))
    globals_head += _record(0x0022, struct.pack("<H", 0))
    name = "S2".encode("latin-1")
    bounds = struct.pack("<iBB", 0, 0, 0) + struct.pack("<BB", len(name), 0) + name
    # Смещение листа проставим после того, как известна длина globals.
    pad = _record(0x00EB, b"\0" * 4200)
    eof = _record(0x000A, b"")
    sheet_at = len(globals_head) + 4 + len(bounds) + len(pad) + len(eof)
    bounds = struct.pack("<iBB", sheet_at, 0, 0) + struct.pack("<BB", len(name), 0) + name
    return bytes(globals_head) + _record(0x0085, bounds) + pad + eof + bytes(sheet)


def _dir_entry(name: str, etype: int, child: int, start: int, size: int) -> bytes:
    raw_name = (name + "\0").encode("utf-16-le")
    entry = bytearray(128)
    entry[0 : len(raw_name)] = raw_name
    struct.pack_into("<HBB", entry, 64, len(raw_name), etype, 1)
    struct.pack_into("<iii", entry, 68, -1, -1, child)
    struct.pack_into("<ii", entry, 116, start, size)
    return bytes(entry)


def _ole(stream: bytes) -> bytes:
    payload = stream + b"\0" * ((-len(stream)) % 512)
    sectors = [payload[index : index + 512] for index in range(0, len(payload), 512)]
    fat = [-1] * 128
    fat[0] = -3
    fat[1] = -2
    first = 2
    for offset, _sector in enumerate(sectors):
        sid = first + offset
        fat[sid] = sid + 1
    fat[first + len(sectors) - 1] = -2
    fat_sector = struct.pack("<128i", *fat)
    directory = _dir_entry("Root Entry", 5, 1, -2, 0)
    directory += _dir_entry("Workbook", 2, -1, first, len(stream))
    directory += b"\0" * (512 - len(directory))
    header = bytearray(512)
    header[0:8] = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
    struct.pack_into("<HH", header, 24, 0x003E, 0x0003)
    header[28:30] = b"\xFE\xFF"
    struct.pack_into("<HH", header, 30, 9, 6)
    struct.pack_into(
        "<iiiiiiii",
        header,
        44,
        1,
        1,
        0,
        4096,
        -2,
        0,
        -2,
        0,
    )
    difat = [0] + [-1] * 108
    struct.pack_into("<109i", header, 76, *difat)
    return bytes(header) + fat_sector + directory + payload


def _s1_text(year: int, month: int) -> str:
    start = f"01.{month:02d}.{year}"
    last = calendar.monthrange(year, month)[1]
    end = f"{last:02d}.{month:02d}.{year}"
    posted = f"15.{month:02d}.{year}"
    lines = [
        "1CClientBankExchange",
        "ВерсияФормата=1.03",
        "Кодировка=UTF-8",
        f"ДатаНачала={start}",
        f"ДатаКонца={end}",
        "СекцияРасчСчет",
        f"ДатаНачала={start}",
        f"ДатаКонца={end}",
        f"РасчСчет={OWN_ACCOUNT}",
        "НачальныйОстаток=0.00",
        f"ВсегоПоступило={AMOUNT}",
        "ВсегоСписано=0.00",
        f"КонечныйОстаток={AMOUNT}",
        "КонецРасчСчет",
        "СекцияДокумент=Платежное поручение",
        "Номер=1",
        f"Дата={posted}",
        f"Сумма={AMOUNT}",
        f"ПлательщикСчет={OTHER_ACCOUNT}",
        f"ДатаПоступило={posted}",
        f"Плательщик={PAYER}",
        "ПлательщикИНН=0000000000",
        f"ПолучательРасчСчет={OWN_ACCOUNT}",
        "Получатель=Synthetic payee",
        "ПолучательИНН=0000000000",
        f"НазначениеПлатежа={PURPOSE}",
        "КонецДокумента",
        "КонецФайла",
        "",
    ]
    return "\n".join(lines)


def _s2_rows(year: int, month: int) -> list[list[tuple[int, str]]]:
    last = calendar.monthrange(year, month)[1]
    start = f"01.{month:02d}.{year}"
    end = f"{last:02d}.{month:02d}.{year}"
    posted = f"15.{month:02d}.{year}"
    return [
        [(0, "Период")],
        [(0, "Документ")],
        [(0, f"Сальдо на {start}"), (11, "0.00")],
        [
            (0, posted),
            (1, "SYN-1"),
            (4, "51"),
            (5, AMOUNT),
            (11, AMOUNT),
        ],
        [
            (0, "Обороты за период"),
            (4, AMOUNT),
            (7, "0.00"),
            (11, AMOUNT),
        ],
        [(0, f"Сальдо на {end}"), (11, AMOUNT)],
    ]


def write_samples(folder: Path, *, year: int, month: int) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    bank = folder / "S1_synthetic.txt"
    card = folder / "S2_synthetic.xls"
    bank.write_text(_s1_text(year, month), encoding="utf-8")
    card.write_bytes(_ole(_workbook_stream(_s2_rows(year, month))))
    return bank, card


def _parse_period(raw: str) -> tuple[int, int]:
    year_text, month_text = raw.split("-", 1)
    year = int(year_text)
    month = int(month_text)
    if year < 2000 or year > 2100 or month < 1 or month > 12:
        raise SystemExit("Период задаётся как ГГГГ-ММ")
    return year, month


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Синтетические S1 и S2 для smoke прогона.")
    parser.add_argument("--window-id", required=True, help="каталог var/<id>/synthetic")
    parser.add_argument("--period", required=True, help="месяц ГГГГ-ММ")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "var",
        help="корень var, по умолчанию var репозитория",
    )
    args = parser.parse_args(argv)
    if not args.window_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("window-id: буквы, цифры, дефис и подчёркивание")
    year, month = _parse_period(args.period)
    folder = args.root / args.window_id / "synthetic"
    bank, card = write_samples(folder, year=year, month=month)
    print(f"s1={bank.name}")
    print(f"s2={card.name}")
    print(f"dir={folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
