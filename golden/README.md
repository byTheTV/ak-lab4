# Golden (фаза A)

Каждая папка — один прогон: транслятор → симулятор.

## Файлы

| Файл | Смысл |
|------|--------|
| `source.tv` | Исходник |
| `expected_output.txt` | Ожидаемый вывод порта DATA_OUT (`Cpu.out_bytes`) |
| `input.txt` | Если есть — байты в `--input` (очередь DATA_IN) |

`hello_user_name`: имя ровно 5 символов + `\n` в `input.txt` (временное упрощение до нормального чтения строки).

Позже можно добавить сюда листинг (`--listing`), дамп `code.bin`/`data.bin`, урезанный `--log`.

Тесты гоняют тот же код, что CLI, но без subprocess; на stdout симулятора не опираемся (там только строка про HALT). Руками, например:

`python -m ak_lab4.translator golden/hello/source.tv -o code.bin --data-out data.bin`

Текстовые файлы в `golden/` — с LF (см. `.gitattributes`).
