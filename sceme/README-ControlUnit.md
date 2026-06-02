# Control Unit — описание схемы и связей

Документ описывает блок-схему **Control Unit (CU)** процессора лабораторной модели `ak-lab4`.  
Схема соответствует реализации в [`src/ak_lab4/cpu.py`](../src/ak_lab4/cpu.py) (классы `ControlUnit`, `Cpu`, `DataPath`).

Связанные материалы:

- Общая модель и журнал: [README.md](../README.md) (раздел «Модель процессора»).
- Схема тракта данных: `Datapath.png` (в этой же папке).
- PNG Control Unit: `control unit.png`.

---

## Содержание

1. [Зачем отдельная схема CU](#1-зачем-отдельная-схема-cu)
2. [Условные обозначения](#2-условные-обозначения)
3. [Один такт — порядок сверху вниз](#3-один-такт--порядок-сверху-вниз)
4. [Соответствие схема ↔ код](#4-соответствие-схема--код)
5. [Блоки схемы](#5-блоки-схемы)
6. [Стрелки и связи (подробно)](#6-стрелки-и-связи-подробно)
7. [Путь инструкции: FETCH → фазы → writeback](#7-путь-инструкции-fetch--фазы--writeback)
8. [Прерывания (trap)](#8-прерывания-trap)
9. [Обновление PC (PX MUX)](#9-обновление-pc-px-mux)
10. [Связь с DataPath](#10-связь-с-datapath)
11. [Superscalar на схеме CU](#11-superscalar-на-схеме-cu)
12. [Журнал симуляции](#12-журнал-симуляции)
13. [Таблица фаз по опкодам](#13-таблица-фаз-по-опкодам)
14. [Типичные ошибки на схеме](#14-типичные-ошибки-на-схеме)

---

## 1. Зачем отдельная схема CU

Процессор в модели разделён на два компонента (как в задании):

| Компонент | В коде | На схеме |
|-----------|--------|----------|
| **Control Unit** | `ControlUnit` + логика в `Cpu` | Такт, FSM, IRQ, выборка, фазы, PC |
| **DataPath** | `DataPath` + стек/DM/порты в `Cpu` | ALU-операции через стек, память, I/O |

**Control Unit** не выполняет арифметику и не хранит операнды на стеке. Он:

- считает такты;
- решает, делать ли FETCH или очередную **микрофазу**;
- обрабатывает **trap** по расписанию;
- формирует **управляющие сигналы** для DataPath;
- выбирает **следующее значение PC**.

Вариант реализации CU: **`hw` (hardwired)** — нет отдельной памяти микропрограмм; последовательность фаз задаётся таблицей в коде (`_scalar_phases_for_opcode`).

---

## 2. Условные обозначения

| Линия | Смысл |
|-------|--------|
| **Сплошная** | Данные/состояние: слово инструкции, opcode, адрес PC, контекст in-flight, номер линии IRQ. |
| **Пунктир** | Управление/события: `fetch`, `clear`, `save`, разрешения IRQ, Control signals в DataPath. |

Регистры на схеме — это **поля модели** `Cpu`, а не отдельные VHDL-регистры:

- `pc`, `sp` — счётчик команд (IM) и указатель стека (DM);
- `pipeline` — один слот **in-flight instruction**;
- `suspended_user_pipeline` — сохранённая пользовательская инструкция при IRQ;
- `irq_pending[]`, `irq_line_value[]`, `irq_enabled`, `interrupt_depth`.

---

## 3. Один такт — порядок сверху вниз

Каждый вызов `Cpu.step()` → `ControlUnit.process_next_tick()` — **ровно один такт**.  
На схеме это блок **Tick** (`ticks++`).

Порядок **фиксированный** (так и рисуйте сверху вниз):

```text
1. Tick (+1)
2. [superscalar] фоновый commit shadow store (BG_STORE) → DataPath
3. Trap Scheduler — события расписания на этот логический такт
4. IRQ control — попытка доставить прерывание
      если IRQ сработал → такт ЗАКАНЧИВАЕТСЯ (issue/фазы не выполняются)
5. Step FSM — иначе:
      pipeline занят?  → одна фаза (Phase FSM → Micro-sequencer)
      pipeline пуст?   → FETCH (или PAR в superscalar)
```

Это главная причина, почему **Tick** идёт в **Trap Scheduler** и **IRQ control**, а не напрямую в Fetch+Decode: выборка — только после проверки IRQ и только если слот in-flight свободен.

---

## 4. Соответствие схема ↔ код

| Блок на схеме | Функции / поля в `cpu.py` |
|---------------|---------------------------|
| Tick | `cpu.ticks += 1` в `process_next_tick` |
| Trap Scheduler | `_apply_irq_schedule_for_current_ticks` |
| irq_pending | `cpu.irq_pending[]`, `cpu.irq_line_value[]` |
| IRQ control | `_try_deliver_irq_before_issue` |
| suspended_user_pipeline | `cpu.suspended_user_pipeline` |
| Fetch + Decode | `_issue_one` → `_make_in_flight` |
| in-flight Instruction | `_InFlightInsn` в `cpu.pipeline` |
| Hardwired phase table | `_scalar_phases_for_opcode` |
| Step FSM | `_step_execution` (ветвление fetch / phase / PAR) |
| Phase FSM | выбор `insn.phases[insn.phase_i]` |
| Micro-sequencer (+branch) | `_run_micro_phase`, `_advance_insn_phase` |
| Control signals | `DataPath.signal_*` |
| Writeback PC | присвоение `self.pc` в фазе `writeback` |
| Vector reader | `_read_vector_target` |
| PX MUX | выбор: обычный PC vs вектор IRQ |
| PC | `cpu.pc` |
| Instruction Memory | `cpu.im` |

Класс `ControlUnit` в коде **тонкий** — вся логика в методах `Cpu`; на схеме CU объединяет их для наглядности.

---

## 5. Блоки схемы

### 5.1. Tick

**Отвечает за:** начало такта симуляции.

**В коде:** первое действие в `process_next_tick` — `cpu.ticks += 1`.

**Стрелки с Tick:**

- → **Trap Scheduler** — применить события JSON с полем `tick`;
- → **IRQ control** — попытка доставки IRQ в начале такта;
- → **Step FSM** — продолжить исполнение, если IRQ не съел такт;
- пунктир → **DataPath** (только при `superscalar`) — `BG_STORE`, фоновый commit отложенной записи.

**Почему Tick не идёт в Fetch+Decode:** fetch — часть шага 5, а не отдельный «клок декодера».

---

### 5.2. Instruction Memory (IM)

**Отвечает за:** память команд (Гарвард), слово 32 бита.

**Стрелки:**

- **PC → IM** — адрес читаемого слова (`IM[PC]`);
- **IM → Fetch+Decode** — слово инструкции при выборке;
- **IM → Vector reader** — слово вектора `IM[1 + irq]` (должно быть `JMP`).

**Раскладка IM** (транслятор):

| Адрес | Содержимое |
|-------|------------|
| 0 | `JMP` на `main` |
| 1 … 8 | векторы IRQ0 … IRQ7 (`JMP` на обработчик) |
| далее | код программы, `defun`, обработчики |

---

### 5.3. PC (Program Counter)

**Отвечает за:** адрес текущей инструкции в IM (в словах, не в байтах).

**Вход:** только **PX MUX** (следующий PC).

**Выходы:**

- → **IM** — адрес для чтения;
- → **Fetch+Decode** — тот же адрес при выборке.

**Важно:** PC **не увеличивается на FETCH**. Инкремент `PC+1` (или jump/call/ret) происходит в **writeback** или при **IRQ trap**.

---

### 5.4. Fetch + Decode

**Отвечает за:** одновременно в один момент:

1. прочитать `word = IM[PC]`;
2. декодировать `unpack_word` → `opcode` (старший байт) + `operand` (24 бита);
3. создать контекст in-flight с таблицей фаз.

**В коде:** `_make_in_flight(pc)` внутри `_issue_one`.

**Входы:**

| Откуда | Что |
|--------|-----|
| IM | машинное слово |
| PC | адрес выборки |
| Step FSM | пунктир **`fetch`** — разрешение выборки (слот пуст) |

**Выход:**

- → **in-flight Instruction** — заполнить слот `pipeline`.

**Журнал:** строка `FETCH`.

**Исключение:** `NOP`, `HALT`, `EI`, `CLI` — в том же такте после FETCH сразу выполняется `writeback` (1 такт на всю инструкцию).

---

### 5.5. in-flight Instruction

**Отвечает за:** единственный слот конвейера — **одна** инструкция «в полёте».

**Поля (логически):**

- `pc`, `word` — откуда взята инструкция;
- `op_byte`, `operand` — декод;
- `phases[]`, `phase_i` — микрофазы;
- `scratch` — временные значения между фазами (результат ALU, адрес, `next_pc` для JZ и т.д.).

**В коде:** `@dataclass _InFlightInsn`, хранится в `cpu.pipeline`.

**Входы:**

| Откуда | Подпись |
|--------|---------|
| Fetch+Decode | новая инструкция |
| Hardwired phase table | `phases[]` (результат таблицы по opcode) |
| suspended_user_pipeline | **`restore on RET`** |
| IRQ control | **`clear`** — очистить слот при trap |

**Выходы:**

| Куда | Подпись |
|------|---------|
| Step FSM | **`pipeline empty?`** / занятость слота |
| Hardwired phase table | **`opcode`** |
| Micro-sequencer | opcode, operand, pc, scratch |
| (опционально) Phase FSM | `phases[]`, `phase_i` |

**Почему не несколько стадий IF/ID/EX:** модель **не классический 5-стадийный** конвейер; за такт выполняется **не больше одной** именованной фазы одной инструкции.

---

### 5.6. Hardwired phase table

**Отвечает за:** по **opcode** вернуть список микрофаз после FETCH.

**В коде:** функция `_scalar_phases_for_opcode(op)`.

**Вход:** `opcode` из in-flight (при decode).

**Выход:** `phases[]` обратно в in-flight (и далее используется Phase FSM).

**Примеры:**

| Opcode | phases[] |
|--------|----------|
| JMP, PUSH_IMM, DUP, … | `writeback` |
| ADD, RET, IN, … | `execute`, `writeback` |
| LOAD, STORE | `execute`, `memory`, `writeback` |
| MUL | `execute`, `mul`, `writeback` |
| DIV, MOD | `execute`, `div`, `writeback` |
| JZ | `execute`, `branch`, `writeback` |
| CALL | `execute`, `writeback` |

**Почему только opcode:** вариант `hw` — фазы **зашиты** в коде, без внешних флагов ALU и без microcode ROM.

**Связь с Phase FSM:** FSM на каждом такте берёт `phases[phase_i]`; после фазы `phase_i` увеличивается.

---

### 5.7. Step FSM

**Отвечает за:** решение «что делать в этом такте», если IRQ не сработал.

**В коде:** `_step_execution`:

```python
if pipeline is not None:
    _tick_pipeline()      # одна фаза
elif superscalar and _try_par_issue():
    ...                   # две инструкции за такт
else:
    _issue_one()          # FETCH
```

**Входы:**

| Откуда | Смысл |
|--------|--------|
| Tick | такт идёт |
| in-flight | слот пуст или занят |
| IRQ control | такт мог быть потрачен на trap (косвенно — Step не вызывается) |

**Выходы:**

| Куда | Подпись |
|------|---------|
| Fetch+Decode | пунктир **`fetch`** — только если `pipeline is None` |
| Phase FSM | **`run 1 phase`** — если слот занят |

**Почему `fetch` именно от Step, а не от Micro-sequencer и не от in-flight:**

- **Micro-sequencer** работает **внутри** занятого слота (фазы);
- **in-flight** — **результат** fetch, а не его инициатор;
- решение «начать новую инструкцию» принимает **Step**, когда слот освободился после последней фазы.

---

### 5.8. Phase FSM

**Отвечает за:** выбрать **имя текущей микрофазы** для in-flight инструкции.

**В коде:** в `_tick_pipeline`: `phase = insn.phases[insn.phase_i]`.

**Входы:**

- от **Step FSM** — разрешение выполнить фазу;
- от **in-flight** / **phase table** — `phases[]` и индекс `phase_i`.

**Выход:**

- → **Micro-sequencer (+branch)** — `current_phase` (`execute`, `memory`, `mul`, `div`, `branch`, `writeback`).

**Журнал:** `PHASE` с именем фазы.

**Обратная связь Phase FSM → Step FSM** на схеме **не обязательна**: после фазы индекс в in-flight увеличивается; на **следующем** такте Step снова смотрит, пуст ли слот.

---

### 5.9. Micro-sequencer (+branch)

**Отвечает за:** выполнение **одной** микрофазы: вызовы DataPath и обновление `scratch`; ветвление **JZ** встроено сюда же (отдельный блок Branch на схеме не нужен).

**В коде:** `_run_micro_phase(insn, phase, log)` + `_advance_insn_phase`.

**Входы:**

| Откуда | Что |
|--------|-----|
| Phase FSM | имя фазы |
| in-flight | opcode, operand, pc, scratch |
| DataPath (пунктир) | например `pop` со стека для JZ/арифметики |

**Выходы:**

| Куда | Что |
|------|-----|
| DataPath | **Control signals** — `signal_push`, `signal_pop`, … |
| Writeback PC | когда `phase == writeback` — новое значение PC |

**Ветвление JZ (почему «+branch»):**

| Фаза | Действие |
|------|----------|
| `execute` | `pop` условие со стека; `branch_taken`; `target_pc` из operand |
| `branch` | `next_pc = target_pc` если взять ветку, иначе `pc+1` |
| `writeback` | `PC = scratch.next_pc` |

**JMP / CALL / RET** не используют фазу `branch` — только `writeback` (и `execute` для подготовки).

**Почему нет флагов ALU (Z/N/C):** стековая модель; условие JZ — **значение на стеке**, не флаги процессора.

---

### 5.10. Control signals → DataPath

**Отвечает за:** интерфейс CU → DP.

**В коде** — только методы `DataPath`:

- `signal_push`, `signal_pop`, `signal_peek_top`
- `signal_read_mem`, `signal_write_mem`
- `signal_read_port`, `signal_write_port`

**Почему пунктир вниз:** исполнительные устройства на другой схеме (DataPath); на CU показываем **наличие управления**, не каждую линию к стеку.

---

### 5.11. Writeback PC

**Отвечает за:** вычисление **следующего PC** в конце инструкции (нормальный путь).

**В коде:** блок `if phase == "writeback"` в `_run_micro_phase` — присвоения `self.pc = ...`.

**Вход:** от **Micro-sequencer** (фаза writeback).

**Типичные случаи:**

| Инструкция | Новый PC |
|------------|----------|
| большинство | `pc + 1` |
| JMP | `operand` (адрес) |
| JZ | `scratch.next_pc` |
| CALL | `scratch.target_pc` (на стек кладётся `ret_pc`) |
| RET | `scratch.ret_addr` со стека + логика ISR |

**Выход:** → **PX MUX** (вход «нормальное исполнение»).

**Почему не рисовать прямую стрелку in-flight → Writeback PC:** PC формируется **действием фазы** writeback, а не «самим регистром инструкции»; данные берутся из `scratch`, но инициатор — Micro-sequencer.

---

### 5.12. PX MUX

**Отвечает за:** выбор источника следующего PC.

**Два входа (достаточно):**

| Вход | Когда |
|------|--------|
| Writeback PC | обычное исполнение / конец инструкции |
| Vector reader | доставка IRQ (приоритет) |

**Выход:** → **PC**.

**Третий вход на MUX не нужен** — в модели нет отдельного «PC+4» помимо writeback.

---

### 5.13. Trap Scheduler

**Отвечает за:** внешнее **расписание** trap (вариант `trap`), не «живые пины».

**В коде:** `cpu.irq_schedule` — массив `{tick, irq, value}` из JSON ([`io_schedule.py`](../src/ak_lab4/io_schedule.py)).

**Входы:**

- **Tick** — на каждом такте;
- пунктир **`irq_schedule events`** — файл расписания.

**Выход:** → **irq_pending** — установить `irq_pending[k] = true` и `irq_line_value[k] = byte`.

**Логический такт события:** `logical_tick = current_tick() - 1` (событие с `tick: 0` — на первом `step`).

---

### 5.14. irq_pending

**Отвечает за:** флаги «на линии k есть необработанный запрос».

**Входы:**

- Trap Scheduler — установка;
- IRQ control — **clear** после доставки.

**Выход:** → IRQ control.

---

### 5.15. IRQ control

**Отвечает за:** доставка **одного** IRQ в начале такта (до FETCH/фаз).

**Условия (все должны выполниться):**

- `irq_enabled == true` (`EI`/`CLI`);
- `interrupt_depth == 0` — **вложенные IRQ не доставляются**;
- есть `irq_pending[k]` (сканируется k = 0 … 7, первый pending).

**В коде:** `_try_deliver_irq_before_issue`.

**Действия при trap:**

1. (ss) `PAR_FLUSH` shadow stores;
2. если `pipeline` не пуст → **save** в `suspended_user_pipeline`, **clear** in-flight;
3. **push** `ret_pc` (= текущий PC) на стек — **DataPath**;
4. **PC** ← адрес из Vector reader;
5. `interrupt_depth++`;
6. байт линии → `_irq_delivered_byte` (первый `IN` в ISR на порту DATA_IN);
7. `irq_pending[k] = false`.

**Входы (пунктир):** `irq_enabled`, `interrupt_depth`.

**Выходы:**

| Куда | Подпись |
|------|---------|
| suspended_user_pipeline | **`save`** |
| in-flight | **`clear`** |
| irq_pending | **`clear`** |
| Step FSM | такт занят trap (issue не идёт) |
| Vector reader | номер линии **`irq`** |
| PX MUX | выбор вектора |
| DataPath | **`push ret_pc`**, **`byte → IN`** |

**Журнал:** `IRQ_TRAP`.

**Почему save не от Fetch+Decode:** прерывание может случиться **между фазами**; сохраняется текущий `pipeline`, а не «только что декодированная» отдельная сущность.

---

### 5.16. suspended_user_pipeline

**Отвечает за:** буфер **одной** пользовательской in-flight инструкции на время ISR.

**Вход:** IRQ control — **`save`**.

**Выход:** in-flight — **`restore on RET`** когда `interrupt_depth` снова 0 после `RET` из обработчика.

**В коде:** `_complete_ret_writeback`.

---

### 5.17. Vector reader

**Отвечает за:** адрес входа в обработчик IRQ.

**В коде:** `_read_vector_target(irq)`:

```text
word = IM[1 + irq]
должен быть opcode JMP
PC ← operand (адрес handler)
```

**Входы:**

- **IM** — слово вектора;
- **IRQ control** — номер линии `k`.

**Выход:** → **PX MUX** (не в Fetch+Decode).

**Почему не PC → Vector reader:** читается **фиксированный слот таблицы векторов**, а не текущий PC.

---

## 6. Стрелки и связи (подробно)

### 6.1. Сводная таблица «откуда → куда»

| От | К | Тип | Почему |
|----|---|-----|--------|
| Tick | Trap Scheduler | управление | расписание на этот такт |
| Tick | IRQ control | управление | try deliver |
| Tick | Step FSM | управление | исполнение |
| Tick | DataPath | пунктир | BG_STORE (ss) |
| PC | IM | адрес | `IM[PC]` |
| PC | Fetch+Decode | адрес | выборка по PC |
| IM | Fetch+Decode | данные | слово инструкции |
| IM | Vector reader | данные | `IM[1+k]` |
| Step FSM | Fetch+Decode | пунктир `fetch` | слот пуст |
| Fetch+Decode | in-flight | данные | новый контекст |
| in-flight | phase table | opcode | lookup фаз |
| phase table | in-flight | phases[] | записать последовательность |
| in-flight | Step FSM | статус | пуст/занят |
| Step FSM | Phase FSM | управление | run 1 phase |
| Phase FSM | Micro-seq | фаза | execute/…/writeback |
| in-flight | Micro-seq | контекст | op, operand, scratch |
| Micro-seq | Control signals | пунктир | signal_* |
| Micro-seq | Writeback PC | управление | фаза writeback |
| Writeback PC | PX MUX | данные | следующий PC |
| Vector reader | PX MUX | данные | PC при IRQ |
| PX MUX | PC | данные | зафиксировать |
| Trap Scheduler | irq_pending | событие | set pending |
| irq_pending | IRQ control | статус | есть запрос |
| IRQ control | irq_pending | clear | обработано |
| IRQ control | in-flight | clear | прервать фазы |
| IRQ control | suspended | save | сохранить pipeline |
| suspended | in-flight | restore | после RET |
| IRQ control | Vector reader | irq # | индекс k |
| IRQ control | DataPath | пунктир | push ret, byte IN |
| IRQ control | Step FSM | управление | такт без issue |

### 6.2. Связи, которых **нет** в модели

| Неправильно | Почему |
|-------------|--------|
| Micro-sequencer → Fetch (`fetch`) | fetch решает Step при пустом слоте |
| in-flight → Fetch | in-flight — результат fetch |
| Fetch → suspended (`save`) | save только при IRQ |
| Fetch → IRQ control | IRQ до fetch, от Tick/логики такта |
| Branch → PX MUX напрямую | JZ: branch → scratch → writeback → PC |
| Status/флаги ALU → Branch | условие JZ со стека |
| PC → Vector reader | вектор из `IM[1+k]` |
| Tick → Fetch напрямую | fetch после IRQ и Step |

---

## 7. Путь инструкции: FETCH → фазы → writeback

### 7.1. Scalar, типичная инструкция (например ADD)

```text
Такт 1:  FETCH     — Step → fetch → IM[PC] → in-flight, phases=[execute, writeback]
Такт 2:  PHASE execute — pop/pop, scratch.result
Такт 3:  PHASE writeback — push result, PC=PC+1, слот освобождён
Такт 4:  FETCH     — следующая инструкция
```

### 7.2. JZ

```text
FETCH
PHASE execute   — pop cond; branch_taken; target_pc
PHASE branch    — next_pc
PHASE writeback — PC = next_pc
```

### 7.3. Прерывание посреди инструкции

```text
Такт N:   PHASE execute (пользовательская инструкция в pipeline)
Такт N+1: IRQ_TRAP — save pipeline → suspended, clear in-flight, push ret_pc, PC ← handler
Такт N+2: FETCH в ISR ...
...
RET из ISR → restore pipeline → продолжение с фазы phase_i
```

---

## 8. Прерывания (trap)

### 8.1. Два разных понятия

| Понятие | Что это |
|---------|---------|
| **Вызов IRQ** | Событие по расписанию → переход в handler |
| **Получение байта** | Первый `IN` в ISR читает `_irq_delivered_byte`, не «магическую очередь» |

### 8.2. IM и обработчики

Транслятор кладёт в `IM[1+k]` слово `JMP` на тело `(interrupt k ...)`.  
Пользовательский код в handler пишется на языке; модель только прыгает по вектору и передаёт байт на линию.

### 8.3. EI / CLI

- `EI` / `CLI` — флаги `irq_enabled`;
- не меняют PC сами по себе (кроме `pc+1` в writeback);
- доставка IRQ всё равно проверяется **в начале каждого такта**.

---

## 9. Обновление PC (PX MUX)

Все источники PC в одной таблице:

| Ситуация | Источник на схеме |
|----------|-------------------|
| Обычное завершение инструкции | Writeback PC → MUX |
| JMP / JZ / CALL / RET | Writeback PC (разная формула) |
| IRQ trap | Vector reader → MUX |
| Во время фаз execute/memory/… | PC **не меняется** |

---

## 10. Связь с DataPath

Control Unit **не рисуют** со всеми проводами к стеку. Достаточно одной шины **Control signals**.

Типичные действия по фазам:

| Фаза / op | Сигналы DP |
|-----------|------------|
| ADD execute | pop, pop |
| ADD writeback | push |
| LOAD execute | pop (addr) |
| LOAD memory | read_mem |
| LOAD writeback | push |
| STORE | pop, pop, write_mem |
| IN | read_port, push |
| OUT | pop, write_port |
| JZ execute | pop |
| CALL writeback | push (ret), PC |
| IRQ | push (ret_pc) |

Детальная схема стека, PUSH MUX, shadow store — в **DataPath** (`Datapath.png`).

---

## 11. Superscalar на схеме CU

Если в варианте включён **superscalar** (`--superscalar`):

| Элемент | Где на CU |
|---------|-----------|
| **PAR** | ветка от Step FSM: две инструкции `IM[PC]`, `IM[PC+1]` за один такт, если слот пуст и пара безопасна |
| **PAR_BLOCK** | Step не делает PAR, если shadow busy |
| **PAR_FLUSH** | пунктир IRQ/HALT → DataPath |
| **BG_STORE** | пунктир Tick → DataPath |

Правила dual issue — консервативная таблица в `can_dual_issue` / `_opcode_breaks_dual_issue`; на схеме CU достаточно подписи у Step FSM.

---

## 12. Журнал симуляции

Запуск:

```bash
python -m ak_lab4.simulator code.bin data.bin --log trace.txt
```

Соответствие блоков CU и строк журнала:

| Строка | Блок схемы |
|--------|------------|
| `FETCH` | Fetch+Decode |
| `PHASE` | Phase FSM + Micro-sequencer |
| `IRQ_TRAP` | IRQ control |
| `PAR` | Step FSM (ss) |
| `PAR_FLUSH` | IRQ / HALT → DataPath |
| `BG_STORE` | Tick → DataPath (ss) |
| `PAR_BLOCK` | Step FSM (ss) |

Колонка `USR` / `ISR` — `interrupt_depth > 0`.

---

## 13. Таблица фаз по опкодам

Полная таблица — в [README.md](../README.md) (раздел «Набор команд и такты»).  
На схеме **Hardwired phase table** — логическое имя этой таблицы.

Кратко:

| Группа | phases после FETCH |
|--------|-------------------|
| NOP, HALT, EI, CLI | writeback (в тот же такт, что FETCH) |
| PUSH_IMM, DUP, DROP, SWAP, JMP | writeback |
| ADD, SUB, EQ, SLT, RET, IN, OUT | execute, writeback |
| LOAD, STORE | execute, memory, writeback |
| MUL | execute, mul, writeback |
| DIV, MOD | execute, div, writeback |
| JZ | execute, branch, writeback |
| CALL | execute, writeback |

---

## 14. Типичные ошибки на схеме

1. **`fetch` от Micro-sequencer** — перенести на **Step FSM**.
2. **`save` от Fetch** — только **IRQ control → suspended**.
3. **Третий вход PX MUX** — оставить два: Writeback + Vector.
4. **Флаги ALU → Branch** — для JZ условие **со стека**.
5. **Tick → Fetch** — Tick → Trap/IRQ/Step, fetch только из Step.
6. **Отдельная память микрокода** — вариант `hw`, её нет.
7. **Несколько in-flight слотов** — в модели **один** `pipeline` (+ один suspend).

---

## Как читать схему целиком (одним абзацем)

**Tick** запускает такт: по расписанию выставляются **irq_pending**, **IRQ control** может перехватить такт и через **Vector reader** и **PX MUX** переключить **PC**, сохранив пользовательскую инструкцию в **suspended**. Иначе **Step FSM** либо выдаёт **fetch** в **Fetch+Decode** (чтение **IM** по **PC** и заполнение **in-flight** с **phase table**), либо через **Phase FSM** запускает **Micro-sequencer**, который шлёт **Control signals** в **DataPath** и в конце **writeback** обновляет **PC** через **Writeback PC** и **PX MUX**. Так повторяется каждый такт до **HALT**.

---

*Документ подготовлен для отчёта по лабораторной работе №4. При изменении модели в `cpu.py` сверяйте этот файл с `process_next_tick`, `_step_execution` и `_try_deliver_irq_before_issue`.*
