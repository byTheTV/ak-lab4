"""CPU: PC/SP, такты, опкоды v0"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import TextIO

from ak_lab4.io_schedule import IrqScheduleEvent
from ak_lab4.isa import (
    NUM_IRQ_LINES,
    OPERAND_MASK,
    Opcode,
    Port,
    sign_extend_operand_i,
    unpack_word,
)
from ak_lab4.memory import DM_SIZE_WORDS, IM_SIZE_WORDS, STACK_BASE


class CpuFault(RuntimeError):
    """Сбой исполнения (стек, PC, деление на 0, ...)"""


def scalar_ticks_for_opcode(op: int) -> int:
    """Число вызовов step() на одну инструкцию в scalar (без PAR)."""
    if op in (
        int(Opcode.NOP),
        int(Opcode.HALT),
        int(Opcode.EI),
        int(Opcode.CLI),
    ):
        return 1
    return 1 + len(_scalar_phases_for_opcode(op))


def _scalar_phases_for_opcode(op: int) -> tuple[str, ...]:
    """Микрофазы исполнения (после такта FETCH — по одной фазе на такт)."""
    if op in (
        int(Opcode.NOP),
        int(Opcode.HALT),
        int(Opcode.EI),
        int(Opcode.CLI),
        int(Opcode.PUSH_IMM),
        int(Opcode.DUP),
        int(Opcode.DROP),
        int(Opcode.SWAP),
        int(Opcode.JMP),
    ):
        return ("writeback",)
    if op in (
        int(Opcode.ADD),
        int(Opcode.SUB),
        int(Opcode.EQ),
        int(Opcode.SLT),
        int(Opcode.RET),
        int(Opcode.IN),
        int(Opcode.OUT),
    ):
        return ("execute", "writeback")
    if op in (
        int(Opcode.LOAD),
        int(Opcode.STORE),
    ):
        return ("execute", "memory", "writeback")
    if op == int(Opcode.MUL):
        return ("execute", "mul", "writeback")
    if op in (
        int(Opcode.DIV),
        int(Opcode.MOD),
    ):
        return ("execute", "div", "writeback")
    if op == int(Opcode.JZ):
        return ("execute", "branch", "writeback")
    if op == int(Opcode.CALL):
        return ("execute", "writeback")
    msg = f"неизвестный опкод 0x{op:02X}"
    raise CpuFault(msg)


@dataclass
class _InFlightInsn:
    pc: int
    word: int
    op_byte: int
    operand: int
    phases: tuple[str, ...]
    phase_i: int = 0
    scratch: dict[str, int] = field(default_factory=dict)

    def phases_remaining(self) -> int:
        return len(self.phases) - self.phase_i


class DataPath:
    """Тракт данных: стек, DM и порты ввода-вывода."""

    def __init__(self, cpu: "Cpu") -> None:
        self._cpu = cpu

    def signal_push(self, value: int) -> None:
        self._cpu._push(value)

    def signal_pop(self) -> int:
        return self._cpu._pop()

    def signal_peek_top(self) -> int:
        return self._cpu._peek_top()

    def signal_read_mem(self, addr: int) -> int:
        a = self._cpu._ensure_dm_addr(addr)
        return (
            self._cpu._read_from_dm_or_shadow(a)
            if self._cpu.superscalar
            else (self._cpu.dm[a] & 0xFFFFFFFF)
        )

    def signal_write_mem(self, addr: int, value: int, log: TextIO | None = None) -> None:
        a = self._cpu._ensure_dm_addr(addr)
        v = value & 0xFFFFFFFF
        if self._cpu.superscalar:
            if len(self._cpu.shadow_stores) >= _SHADOW_STORE_CAPACITY:
                self._cpu._flush_shadow_stores(log, reason="overflow")
            self._cpu.shadow_stores.append((a, v))
            self._cpu.shadow_busy_ticks = _SHADOW_STORE_TICKS
            self._cpu._note_store_visibility(a, v)
            return
        self._cpu.dm[a] = v

    def signal_read_port(self, port: int) -> int:
        return self._cpu._read_port_in(port)

    def signal_write_port(self, port: int, value: int) -> None:
        if port == int(Port.DATA_OUT):
            self._cpu.out_bytes.append(value & 0xFF)


class ControlUnit:
    """Блок управления: тактирование, выборка, IRQ, запуск микрофаз."""

    def __init__(self, cpu: "Cpu") -> None:
        self._cpu = cpu

    def current_tick(self) -> int:
        return self._cpu.ticks

    def process_next_tick(self, log: TextIO | None = None) -> None:
        cpu = self._cpu
        if cpu.halted:
            return

        cpu.ticks += 1
        if cpu.superscalar:
            cpu._tick_shadow_background(log)
        cpu._apply_irq_schedule_for_current_ticks()
        if cpu._try_deliver_irq_before_issue(log):
            return
        cpu._step_execution(log)


_SHADOW_STORE_CAPACITY = 1
_SHADOW_STORE_TICKS = 2


def _opcode_breaks_dual_issue(op: int) -> bool:
    """Вторая инструкция в паре не выдаётся вместе с ветвлением/остановом/портами IRQ."""
    return op in (
        int(Opcode.JMP),
        int(Opcode.JZ),
        int(Opcode.CALL),
        int(Opcode.RET),
        int(Opcode.HALT),
        int(Opcode.EI),
        int(Opcode.CLI),
        int(Opcode.OUT),
    )


def can_dual_issue(op0: int, op1: int) -> bool:
    """
    Консервативная проверка независимости пары.
    Разрешаем пары без конфликтов по стеку и без операций управления/портов

    Можно было бы динамически анализировать зависимости (scoreboard) и решать на лету,
    можно ли выдать две инструкции вместе
    Это дало бы больше параллелизма, но сильно усложнило бы код
    Плюс поведение стало бы менее предсказуемым, поэтому решил сделать так
    """
    if _opcode_breaks_dual_issue(op0) or _opcode_breaks_dual_issue(op1):
        return False

    n0 = int(Opcode.NOP)
    n1 = int(Opcode.PUSH_IMM)
    d = int(Opcode.DUP)
    dr = int(Opcode.DROP)
    ld = int(Opcode.LOAD)
    st = int(Opcode.STORE)
    sw = int(Opcode.SWAP)
    add = int(Opcode.ADD)
    sub = int(Opcode.SUB)
    mul = int(Opcode.MUL)
    div = int(Opcode.DIV)
    mod = int(Opcode.MOD)
    eq = int(Opcode.EQ)
    slt = int(Opcode.SLT)
    inn = int(Opcode.IN)
    allowed_pairs = {
        (n0, n0),
        (n0, n1),
        (n1, n0),
        (n1, n1),
        (d, n0),
        (n0, d),
        (dr, n0),
        (n0, dr),
        (ld, n0),
        (n0, ld),
        (st, n0),
        (n0, st),
        (sw, n0),
        (n0, sw),
        (n1, st),
        (d, st),
        (ld, st),
        (add, st),
        (sub, st),
        (mul, st),
        (div, st),
        (mod, st),
        (eq, st),
        (slt, st),
        (inn, st),
    }
    return (op0, op1) in allowed_pairs


def _blocked_by_shadow_busy(op1: int, shadow_busy_ticks: int) -> bool:
    """
    Приближение к модели с конвейерной занятостью памяти:
    пока фоновой store не завершён, не выдаём пару со вторым STORE.
    """
    if shadow_busy_ticks <= 0:
        return False
    return op1 == int(Opcode.STORE)


@dataclass
class Cpu:
    """Гарвард: IM/DM, адрес словами"""

    im: list[int] = field(default_factory=lambda: [0] * IM_SIZE_WORDS)
    dm: list[int] = field(default_factory=lambda: [0] * DM_SIZE_WORDS)
    pc: int = 0
    sp: int = STACK_BASE
    ticks: int = 0
    halted: bool = False

    # True: за один step - до двух последовательных инструкций (при отсутствии конфликтов).
    superscalar: bool = False
    pipeline: _InFlightInsn | None = field(default=None, repr=False)
    suspended_user_pipeline: _InFlightInsn | None = field(default=None, repr=False)

    # DATA_IN: очередь байт слева; пусто -> на стек -1 (EOF)
    input_queue: deque[int] = field(default_factory=deque)

    # DATA_OUT: байты из младшего октета слова
    out_bytes: list[int] = field(default_factory=list)

    # trap по тактам
    irq_schedule: tuple[IrqScheduleEvent, ...] = field(default_factory=tuple)
    _schedule_i: int = field(default=0, repr=False)

    # запрос по линии + байт на линии (не stdin)
    irq_pending: list[bool] = field(default_factory=lambda: [False] * NUM_IRQ_LINES)
    irq_line_value: list[int] = field(default_factory=lambda: [0] * NUM_IRQ_LINES)
    irq_enabled: bool = True
    interrupt_depth: int = 0

    # байт для первого IN в ISR после доставки IRQ
    _irq_delivered_byte: int | None = field(default=None, repr=False)

    # AC_SHADOW для stack-варианта в superscalar-режиме
    shadow_stores: list[tuple[int, int]] = field(default_factory=list, repr=False)
    shadow_busy_ticks: int = field(default=0, repr=False)
    last_load_addr: int | None = field(default=None, repr=False)
    last_load_value: int | None = field(default=None, repr=False)
    data_path: DataPath = field(init=False, repr=False)
    control_unit: ControlUnit = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.data_path = DataPath(self)
        self.control_unit = ControlUnit(self)

    def _invalidate_last_load(self) -> None:
        self.last_load_addr = None
        self.last_load_value = None

    def _note_store_visibility(self, addr: int, value: int) -> None:
        """Обновить кэш последней загрузки после записи в память/теневую очередь."""
        if self.last_load_addr == addr:
            self.last_load_value = value & 0xFFFFFFFF

    def _read_from_dm_or_shadow(self, addr: int) -> int:
        if self.shadow_stores:
            sh_addr, sh_val = self.shadow_stores[0]
            if sh_addr == addr:
                return sh_val & 0xFFFFFFFF
        return self.dm[addr] & 0xFFFFFFFF

    def _tick_shadow_background(self, log: TextIO | None = None) -> None:
        """Фоновая запись из shadow в DM по 1 шагу симулятора."""
        if not self.shadow_stores or self.shadow_busy_ticks <= 0:
            return
        self.shadow_busy_ticks -= 1
        if self.shadow_busy_ticks != 0:
            return
        addr, value = self.shadow_stores[0]
        a = self._ensure_dm_addr(addr)
        self.dm[a] = value & 0xFFFFFFFF
        self._note_store_visibility(a, value)
        if log is not None:
            log.write(
                f"{self.ticks}\tBG_STORE\t{a}:{value & 0xFFFFFFFF:08X}\t{self._exec_mode()}\n",
            )
        self.shadow_stores.clear()

    def _flush_shadow_stores(
        self,
        log: TextIO | None = None,
        *,
        reason: str,
    ) -> bool:
        """Принудительно закоммитить shadow store без изменения глобального ticks."""
        if not self.shadow_stores:
            return False
        if log is not None:
            payload = "\t".join(f"{a}:{v:08X}" for a, v in self.shadow_stores)
            log.write(
                f"{self.ticks}\tPAR_FLUSH\t{reason}\t{payload}\t{self._exec_mode()}\n",
            )
        for addr, value in self.shadow_stores:
            a = self._ensure_dm_addr(addr)
            self.dm[a] = value & 0xFFFFFFFF
            self._note_store_visibility(a, value)
        self.shadow_stores.clear()
        self.shadow_busy_ticks = 0
        return True

    def _apply_irq_schedule_for_current_ticks(self) -> None:
        """Применить события, назначенные на логический такт (step index)."""
        logical_tick = self.control_unit.current_tick() - 1
        while self._schedule_i < len(self.irq_schedule):
            ev = self.irq_schedule[self._schedule_i]
            if ev.tick < logical_tick:
                # Пропущенное событие: сдвигаем указатель, чтобы не зациклиться.
                self._schedule_i += 1
                continue
            if ev.tick > logical_tick:
                break
            irq = ev.irq
            if 0 <= irq < NUM_IRQ_LINES:
                v = ev.value & 0xFF
                self.irq_line_value[irq] = v
                self.irq_pending[irq] = True
            self._schedule_i += 1

    def _read_vector_target(self, irq: int) -> int:
        idx = 1 + irq
        if idx < 0 or idx >= IM_SIZE_WORDS:
            msg = f"вектор IRQ{irq}: слово @{idx} вне IM"
            raise CpuFault(msg)
        op_b, opnd = unpack_word(self.im[idx])
        if op_b != int(Opcode.JMP):
            msg = f"вектор IRQ{irq}: в IM[{idx}] должен быть jmp"
            raise CpuFault(msg)
        return self._ensure_im_pc(opnd & OPERAND_MASK)

    def _read_port_in(self, port: int) -> int:
        """чтение IN по номеру порта"""
        if port == int(Port.DATA_IN):
            if self._irq_delivered_byte is not None:
                b = self._irq_delivered_byte & 0xFF
                self._irq_delivered_byte = None
                return b
            if self.input_queue:
                return self.input_queue.popleft() & 0xFF
            return -1
        return 0

    def _ensure_dm_addr(self, addr: int) -> int:
        if addr < 0 or addr >= DM_SIZE_WORDS:
            msg = f"DM: адрес {addr} мимо диапазона"
            raise CpuFault(msg)
        return addr

    def _ensure_im_pc(self, addr: int) -> int:
        if addr < 0 or addr >= IM_SIZE_WORDS:
            msg = f"PC {addr} вне IM"
            raise CpuFault(msg)
        return addr

    def _push(self, value: int) -> None:
        v = value & 0xFFFFFFFF
        if self.sp >= DM_SIZE_WORDS:
            msg = "стек переполнен"
            raise CpuFault(msg)
        a = self._ensure_dm_addr(self.sp)
        self.dm[a] = v
        self.sp += 1

    def _pop(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "pop из пустого стека"
            raise CpuFault(msg)
        self.sp -= 1
        a = self._ensure_dm_addr(self.sp)
        return self.dm[a] & 0xFFFFFFFF

    def _peek_top(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "dup при пустом стеке"
            raise CpuFault(msg)
        a = self._ensure_dm_addr(self.sp - 1)
        return self.dm[a] & 0xFFFFFFFF

    def _exec_mode(self) -> str:
        return "ISR" if self.interrupt_depth > 0 else "USR"

    def _make_in_flight(self, pc0: int) -> _InFlightInsn:
        word = self.im[pc0] & 0xFFFFFFFF
        op_byte, operand = unpack_word(word)
        return _InFlightInsn(
            pc=pc0,
            word=word,
            op_byte=op_byte,
            operand=operand,
            phases=_scalar_phases_for_opcode(op_byte),
        )

    def _log_fetch(self, insn: _InFlightInsn, log: TextIO | None) -> None:
        if log is None:
            return
        log.write(f"{self.ticks}\tFETCH\t{insn.pc}\t{insn.word:08X}\t{self._exec_mode()}\n")

    def _log_phase(self, insn: _InFlightInsn, phase: str, remaining: int, log: TextIO | None) -> None:
        if log is None:
            return
        log.write(
            f"{self.ticks}\tPHASE\t{insn.phase_i}\t{phase}\t{remaining}\t{self._exec_mode()}\n",
        )

    def _advance_insn_phase(self, insn: _InFlightInsn, phase: str, log: TextIO | None) -> None:
        self._run_micro_phase(insn, phase, log)
        insn.phase_i += 1
        self._log_phase(insn, phase, insn.phases_remaining(), log)

    def _finish_insn_phases(self, insn: _InFlightInsn, log: TextIO | None) -> None:
        """Все оставшиеся фазы инструкции (в рамках текущего такта)."""
        while insn.phases_remaining() > 0:
            phase = insn.phases[insn.phase_i]
            self._advance_insn_phase(insn, phase, log)

    def _issue_one(self, log: TextIO | None) -> None:
        """FETCH; NOP/HALT/EI/CLI — same-tick FETCH+writeback (1 тик)."""
        insn = self._make_in_flight(self._ensure_im_pc(self.pc))
        self._log_fetch(insn, log)
        if insn.phases == ("writeback",) and insn.op_byte in (
            int(Opcode.NOP),
            int(Opcode.HALT),
            int(Opcode.EI),
            int(Opcode.CLI),
        ):
            self._advance_insn_phase(insn, "writeback", log)
            return
        self.pipeline = insn

    def _tick_pipeline(self, log: TextIO | None) -> None:
        """Один такт: одна фаза in-flight инструкции."""
        insn = self.pipeline
        if insn is None or insn.phases_remaining() <= 0:
            self.pipeline = None
            return
        phase = insn.phases[insn.phase_i]
        self._advance_insn_phase(insn, phase, log)
        self.pipeline = insn if insn.phases_remaining() > 0 else None

    def _try_par_issue(self, log: TextIO | None) -> bool:
        """Двойная выдача: PAR + завершение пары в текущем такте."""
        pc0 = self._ensure_im_pc(self.pc)
        word0 = self.im[pc0] & 0xFFFFFFFF
        op0, _ = unpack_word(word0)

        if _opcode_breaks_dual_issue(op0):
            return False

        pc1 = pc0 + 1
        if pc1 >= IM_SIZE_WORDS:
            return False

        word1 = self.im[pc1] & 0xFFFFFFFF
        op1, _ = unpack_word(word1)

        if _opcode_breaks_dual_issue(op1):
            return False
        if not can_dual_issue(op0, op1):
            return False
        if _blocked_by_shadow_busy(op1, self.shadow_busy_ticks):
            if log is not None:
                log.write(f"{self.ticks}\tPAR_BLOCK\tshadow_busy\t{self._exec_mode()}\n")
            return False

        if log is not None:
            log.write(
                f"{self.ticks}\tPAR\t{pc0}\t{word0:08X}\t{pc1}\t{word1:08X}\t{self._exec_mode()}\n",
            )

        insn0 = self._make_in_flight(pc0)
        insn1 = self._make_in_flight(pc1)
        for insn in (insn0, insn1):
            self._finish_insn_phases(insn, log)
            if self.halted:
                return True
        return True

    def _step_execution(self, log: TextIO | None) -> None:
        if self.pipeline is not None:
            self._tick_pipeline(log)
            return
        if self.superscalar and self.interrupt_depth == 0 and self._try_par_issue(log):
            return
        self._issue_one(log)

    def _run_micro_phase(self, insn: _InFlightInsn, phase: str, log: TextIO | None) -> None:
        """Один микрошаг активной инструкции."""
        op = insn.op_byte
        operand = insn.operand
        next_pc = insn.pc + 1

        if phase == "execute":
            if op == int(Opcode.ADD):
                x1 = self.data_path.signal_pop()
                y = self.data_path.signal_pop()
                insn.scratch["result"] = (y + x1) & 0xFFFFFFFF
                return
            if op == int(Opcode.SUB):
                x1 = self.data_path.signal_pop()
                y = self.data_path.signal_pop()
                insn.scratch["result"] = (y - x1) & 0xFFFFFFFF
                return
            if op == int(Opcode.EQ):
                x1 = self.data_path.signal_pop() & 0xFFFFFFFF
                y = self.data_path.signal_pop() & 0xFFFFFFFF
                insn.scratch["result"] = 1 if y == x1 else 0
                return
            if op == int(Opcode.SLT):
                b = self.data_path.signal_pop() & 0xFFFFFFFF
                a = self.data_path.signal_pop() & 0xFFFFFFFF
                insn.scratch["result"] = 1 if _signed32(a) < _signed32(b) else 0
                return
            if op == int(Opcode.RET):
                insn.scratch["ret_addr"] = self._ensure_im_pc(
                    self.data_path.signal_pop() & 0xFFFFFFFF,
                )
                return
            if op == int(Opcode.IN):
                port = operand & 0xFFFF
                insn.scratch["in_val"] = _unsigned32(self.data_path.signal_read_port(port))
                return
            if op == int(Opcode.OUT):
                insn.scratch["out_val"] = self.data_path.signal_pop() & 0xFFFFFFFF
                insn.scratch["out_port"] = operand & 0xFFFF
                return
            if op == int(Opcode.LOAD):
                insn.scratch["addr"] = self._ensure_dm_addr(self.data_path.signal_pop())
                return
            if op == int(Opcode.STORE):
                insn.scratch["store_val"] = self.data_path.signal_pop() & 0xFFFFFFFF
                return
            if op == int(Opcode.MUL):
                x1 = self.data_path.signal_pop()
                y = self.data_path.signal_pop()
                insn.scratch["mul_l"] = _signed32(y)
                insn.scratch["mul_r"] = _signed32(x1)
                return
            if op in (int(Opcode.DIV), int(Opcode.MOD)):
                x1 = self.data_path.signal_pop()
                y = self.data_path.signal_pop()
                if x1 == 0:
                    if op == int(Opcode.DIV):
                        raise CpuFault("деление на 0")
                    raise CpuFault("mod и делитель 0")
                insn.scratch["div_l"] = _signed32(y)
                insn.scratch["div_r"] = _signed32(x1)
                return
            if op == int(Opcode.JZ):
                cond = self.data_path.signal_pop() & 0xFFFFFFFF
                insn.scratch["branch_taken"] = 1 if cond == 0 else 0
                insn.scratch["target_pc"] = self._ensure_im_pc(operand & OPERAND_MASK)
                return
            if op == int(Opcode.CALL):
                insn.scratch["target_pc"] = self._ensure_im_pc(operand & OPERAND_MASK)
                insn.scratch["ret_pc"] = next_pc & 0xFFFFFFFF
                return
            msg = f"execute-stage не поддерживает опкод 0x{op:02X}"
            raise CpuFault(msg)

        if phase == "memory":
            if op == int(Opcode.LOAD):
                a = insn.scratch["addr"]
                if (
                    self.superscalar
                    and self.last_load_addr == a
                    and self.last_load_value is not None
                ):
                    val = self.last_load_value & 0xFFFFFFFF
                else:
                    val = self.data_path.signal_read_mem(a)
                insn.scratch["load_val"] = val & 0xFFFFFFFF
                return
            if op == int(Opcode.STORE):
                insn.scratch["store_addr"] = self._ensure_dm_addr(self.data_path.signal_pop())
                return
            msg = f"memory-stage не поддерживает опкод 0x{op:02X}"
            raise CpuFault(msg)

        if phase == "mul":
            insn.scratch["result"] = _unsigned32(
                insn.scratch["mul_l"] * insn.scratch["mul_r"],
            )
            return

        if phase == "div":
            div_q = math.trunc(insn.scratch["div_l"] / insn.scratch["div_r"])
            if op == int(Opcode.DIV):
                insn.scratch["result"] = _unsigned32(div_q)
            else:
                rem = insn.scratch["div_l"] - div_q * insn.scratch["div_r"]
                insn.scratch["result"] = _unsigned32(rem)
            return

        if phase == "branch":
            insn.scratch["next_pc"] = (
                insn.scratch["target_pc"] if insn.scratch["branch_taken"] else next_pc
            )
            return

        if phase != "writeback":
            msg = f"неизвестная микрофаза {phase!r}"
            raise CpuFault(msg)

        if op == int(Opcode.NOP):
            self.pc = next_pc
            return
        if op == int(Opcode.HALT):
            if self.superscalar:
                self._flush_shadow_stores(log, reason="halt")
            self.halted = True
            self.pc = next_pc
            return
        if op == int(Opcode.EI):
            self.irq_enabled = True
            self.pc = next_pc
            return
        if op == int(Opcode.CLI):
            self.irq_enabled = False
            self.pc = next_pc
            return
        if op == int(Opcode.PUSH_IMM):
            self.data_path.signal_push(sign_extend_operand_i(operand) & 0xFFFFFFFF)
            self.pc = next_pc
            return
        if op == int(Opcode.DUP):
            self.data_path.signal_push(self.data_path.signal_peek_top())
            self.pc = next_pc
            return
        if op == int(Opcode.DROP):
            _ = self.data_path.signal_pop()
            self._invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.SWAP):
            top = self.data_path.signal_pop()
            below = self.data_path.signal_pop()
            self.data_path.signal_push(top)
            self.data_path.signal_push(below)
            self._invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.JMP):
            self.pc = self._ensure_im_pc(operand & OPERAND_MASK)
            return
        if op == int(Opcode.ADD) or op == int(Opcode.SUB):
            self.data_path.signal_push(insn.scratch["result"] & 0xFFFFFFFF)
            self._invalidate_last_load()
            self.pc = next_pc
            return
        if op in (int(Opcode.EQ), int(Opcode.SLT)):
            self.data_path.signal_push(insn.scratch["result"] & 0xFFFFFFFF)
            self._invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.RET):
            self._complete_ret_writeback(insn)
            return
        if op == int(Opcode.IN):
            self.data_path.signal_push(insn.scratch["in_val"] & 0xFFFFFFFF)
            self._invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.OUT):
            self.data_path.signal_write_port(insn.scratch["out_port"], insn.scratch["out_val"])
            self._invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.LOAD):
            val = insn.scratch["load_val"] & 0xFFFFFFFF
            self.data_path.signal_push(val)
            if self.superscalar:
                self.last_load_addr = insn.scratch["addr"]
                self.last_load_value = val
            self.pc = next_pc
            return
        if op == int(Opcode.STORE):
            a = insn.scratch["store_addr"]
            v = insn.scratch["store_val"] & 0xFFFFFFFF
            self.data_path.signal_write_mem(a, v, log)
            self.pc = next_pc
            return
        if op in (int(Opcode.MUL), int(Opcode.DIV), int(Opcode.MOD)):
            self.data_path.signal_push(insn.scratch["result"] & 0xFFFFFFFF)
            self._invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.JZ):
            self._invalidate_last_load()
            self.pc = insn.scratch["next_pc"]
            return
        if op == int(Opcode.CALL):
            self.data_path.signal_push(insn.scratch["ret_pc"])
            self._invalidate_last_load()
            self.pc = insn.scratch["target_pc"]
            return
        word = insn.word & 0xFFFFFFFF
        msg = (
            f"writeback-stage не поддерживает опкод 0x{op:02X} "
            f"@PC={insn.pc} word={word:08X}"
        )
        raise CpuFault(msg)

    def _complete_ret_writeback(self, insn: _InFlightInsn) -> None:
        if self.interrupt_depth > 0:
            self.interrupt_depth -= 1
        self._invalidate_last_load()
        self.pc = insn.scratch["ret_addr"]
        if self.interrupt_depth == 0 and self.suspended_user_pipeline:
            self.pipeline = self.suspended_user_pipeline
            self.suspended_user_pipeline = None

    def step(self, log: TextIO | None = None) -> None:
        """Один тик модели через ControlUnit."""
        self.control_unit.process_next_tick(log)

    def _try_deliver_irq_before_issue(self, log: TextIO | None = None) -> bool:
        """доставка IRQ в начале тика (до issue)."""
        if not self.irq_enabled:
            return False
        if self.interrupt_depth > 0:
            return False
        for irq in range(NUM_IRQ_LINES):
            if not self.irq_pending[irq]:
                continue
            if self.superscalar:
                self._flush_shadow_stores(log, reason="irq")
            ret_pc = self.pc
            if self.pipeline is not None:
                self.suspended_user_pipeline = self.pipeline
                self.pipeline = None
            self._push(ret_pc & 0xFFFFFFFF)
            self.pc = self._read_vector_target(irq)
            self.interrupt_depth += 1
            self._irq_delivered_byte = self.irq_line_value[irq] & 0xFF
            self.irq_pending[irq] = False
            if log is not None:
                log.write(f"{self.ticks}\tIRQ_TRAP\t{irq}\t{self._exec_mode()}\n")
            return True
        return False


def _signed32(u: int) -> int:
    u &= 0xFFFFFFFF
    return u - 0x100000000 if u >= 0x80000000 else u


def _unsigned32(i: int) -> int:
    return i & 0xFFFFFFFF


def init_memory_from_segments(
    code_words: list[int],
    data_words: list[int],
) -> tuple[list[int], list[int]]:
    """залить IM с PC=0 и DM с адреса 0"""
    im = [0] * IM_SIZE_WORDS
    dm = [0] * DM_SIZE_WORDS
    for i, w in enumerate(code_words):
        if i >= IM_SIZE_WORDS:
            msg = "сегмент кода не влезает в IM"
            raise CpuFault(msg)
        im[i] = w & 0xFFFFFFFF
    for i, w in enumerate(data_words):
        if i >= DM_SIZE_WORDS:
            msg = "сегмент данных не влезает в DM"
            raise CpuFault(msg)
        dm[i] = w & 0xFFFFFFFF
    return im, dm


def run_program(
    cpu: Cpu,
    *,
    max_ticks: int,
    log: TextIO | None = None,
) -> None:
    """крутить step до halt/fault/лимита тактов"""
    while not cpu.halted:
        if cpu.ticks >= max_ticks:
            msg = f"лимит тактов ({max_ticks})"
            raise CpuFault(msg)
        cpu.step(log=log)
