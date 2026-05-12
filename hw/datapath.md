# DataPath (hw)

Схема отражает аппаратный тракт данных для варианта `stack | harv | port | trap`.

```mermaid
flowchart LR
    IM["Instruction Memory (IM)\nword[31:0]"] -->|instr_word| IR["IR (Instruction Register)"]
    IR -->|opcode[31:24], operand[23:0]| CU["Control Unit"]

    PC["PC register"] -->|im_addr| IM
    CU -->|pc_sel, pc_we| PC

    SP["SP register"] -->|sp_addr| DM["Data Memory (DM)\nword[31:0]"]
    CU -->|sp_inc, sp_dec| SP

    DM -->|dm_rdata| TOS["TOS latch"]
    DM -->|dm_rdata| NOS["NOS latch"]
    TOS --> ALU["ALU\nADD SUB MUL DIV MOD EQ SLT"]
    NOS --> ALU
    ALU -->|alu_res| WB["Writeback MUX"]

    IR -->|imm24 sign-extend| IMM["IMM extender"]
    IMM --> WB
    DM -->|dm_rdata (LOAD)| WB

    WB -->|wb_data| DM
    CU -->|dm_we, dm_re, wb_sel| DM

    IRQ["IRQ pending + latch"] --> CU
    INP["DATA_IN buffer"] --> IO["Port I/O block"]
    TOS --> IO
    IO -->|in_data| WB
    IO -->|out_byte| OUT["DATA_OUT buffer"]
    CU -->|in_en, out_en, port_sel| IO
```

## Регистры и флаги

- `PC`: адрес текущей инструкции в `IM`.
- `SP`: указатель вершины стековой области в `DM`.
- `IR`: защёлка слова инструкции.
- `TOS`, `NOS`: верхние элементы стека (операндные защёлки АЛУ).
- Флаги прерываний (минимум): `irq_enabled`, `interrupt_depth`, `irq_pending[k]`.

## Основные управляющие сигналы DataPath

- `pc_we`, `pc_sel`: запись/источник нового `PC` (`PC+1`, `JMP`, `CALL/RET`, `IRQ vector`).
- `sp_inc`, `sp_dec`: изменение указателя стека при push/pop.
- `dm_re`, `dm_we`: чтение/запись в память данных.
- `wb_sel`: выбор источника записи в стек (`ALU`, `IMM`, `DM`, `IN`).
- `alu_op`: код операции АЛУ.
- `in_en`, `out_en`, `port_sel`: управление портовым вводом-выводом.

## Примечание по superscalar

В режиме `superscalar` архитектурное состояние DataPath остаётся тем же; добавляется теневой буфер отложенных записей (`shadow_stores`) как внешний к основной DM механизм commit/flush.
