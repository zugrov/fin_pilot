"""Заглушка xlrd только для стенда приёмки. Не для продакшена."""

STUB_MESSAGE = "xls reading is disabled on the staging stand"


class XLRDError(RuntimeError):
    pass


def open_workbook(*args, **kwargs):
    raise RuntimeError(STUB_MESSAGE)
