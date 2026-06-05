"""Модель процессора: ControlUnit + DataPath (Гарвард, stack, tick)."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TextIO

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

if TYPE_CHECKING:
    pass

_SHADOW_STORE_CAPACITY = 1
_SHADOW_STORE_TICKS = 2


class MachineFault(RuntimeError):
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
    raise MachineFault(msg)


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
    Теоретически можно было бы на лету проверять пару перед PAR:
    - стек: сколько каждая инструкция снимает/кладёт (ADD −2+1, PUSH +1, STORE −2…),
      хватит ли глубины после op0, чтобы op1 не уперлась в пустой стек;
    - память: не читает ли op1 адрес, который op0 ещё не записал (LOAD после STORE
      в shadow), или не пишут ли обе в одно и то же;
    - плюс отсечь ветвления, HALT, порты — они ломают последовательный PC.

    Но решил, что проще сделать через whitelist, чтобы не усложнять код
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
    if shadow_busy_ticks <= 0:
        return False
    return op1 == int(Opcode.STORE)


def _signed32(u: int) -> int:
    u &= 0xFFFFFFFF
    return u - 0x100000000 if u >= 0x80000000 else u


def _unsigned32(i: int) -> int:
    return i & 0xFFFFFFFF


class DataPath:
    """Тракт данных: стек, DM, порты, store buffer (shadow)."""

    def __init__(
        self,
        *,
        dm: list[int] | None = None,
        sp: int = STACK_BASE,
        input_queue: deque[int] | None = None,
        out_bytes: list[int] | None = None,
    ) -> None:
        self.dm: list[int] = dm if dm is not None else [0] * DM_SIZE_WORDS
        self.sp = sp
        self.input_queue: deque[int] = input_queue if input_queue is not None else deque()  # Port IN
        self.out_bytes: list[int] = out_bytes if out_bytes is not None else []  # Port OUT
        self.shadow_stores: list[tuple[int, int]] = []  # deferred store: (addr, val)
        self.shadow_busy_ticks = 0  # тики до BG commit в DM
        self.last_load_addr: int | None = None  # DLE bypass: последний LOAD
        self.last_load_value: int | None = None
        self._irq_delivered_byte: int | None = None  # байт линии для первого IN в ISR
        self._cu: ControlUnit | None = None  # ссылка для superscalar и журнала

    def _cu_ref(self) -> ControlUnit:
        if self._cu is None:
            msg = "DataPath не привязан к ControlUnit"
            raise MachineFault(msg)
        return self._cu

    def ensure_dm_addr(self, addr: int) -> int:
        if addr < 0 or addr >= DM_SIZE_WORDS:
            msg = f"DM: адрес {addr} мимо диапазона"
            raise MachineFault(msg)
        return addr

    def invalidate_last_load(self) -> None:
        self.last_load_addr = None
        self.last_load_value = None

    def note_store_visibility(self, addr: int, value: int) -> None:
        if self.last_load_addr == addr:
            self.last_load_value = value & 0xFFFFFFFF

    def read_from_dm_or_shadow(self, addr: int) -> int:
        if self.shadow_stores:
            sh_addr, sh_val = self.shadow_stores[0]
            if sh_addr == addr:
                return sh_val & 0xFFFFFFFF
        return self.dm[addr] & 0xFFFFFFFF

    def tick_shadow_background(self, log: TextIO | None = None) -> None:
        cu = self._cu_ref()
        if not self.shadow_stores or self.shadow_busy_ticks <= 0:
            return
        self.shadow_busy_ticks -= 1
        if self.shadow_busy_ticks != 0:
            return
        addr, value = self.shadow_stores[0]
        a = self.ensure_dm_addr(addr)
        self.dm[a] = value & 0xFFFFFFFF
        self.note_store_visibility(a, value)
        if log is not None:
            log.write(
                f"{cu.ticks}\tBG_STORE\t{a}:{value & 0xFFFFFFFF:08X}\t{cu.exec_mode()}\n",
            )
        self.shadow_stores.clear()

    def flush_shadow_stores(
        self,
        log: TextIO | None = None,
        *,
        reason: str,
    ) -> bool:
        cu = self._cu_ref()
        if not self.shadow_stores:
            return False
        if log is not None:
            payload = "\t".join(f"{a}:{v:08X}" for a, v in self.shadow_stores)
            log.write(
                f"{cu.ticks}\tPAR_FLUSH\t{reason}\t{payload}\t{cu.exec_mode()}\n",
            )
        for addr, value in self.shadow_stores:
            a = self.ensure_dm_addr(addr)
            self.dm[a] = value & 0xFFFFFFFF
            self.note_store_visibility(a, value)
        self.shadow_stores.clear()
        self.shadow_busy_ticks = 0
        return True

    def signal_push(self, value: int) -> None:
        v = value & 0xFFFFFFFF
        if self.sp >= DM_SIZE_WORDS:
            msg = "стек переполнен"
            raise MachineFault(msg)
        a = self.ensure_dm_addr(self.sp)
        self.dm[a] = v
        self.sp += 1

    def signal_pop(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "pop из пустого стека"
            raise MachineFault(msg)
        self.sp -= 1
        a = self.ensure_dm_addr(self.sp)
        return self.dm[a] & 0xFFFFFFFF

    def signal_peek_top(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "dup при пустом стеке"
            raise MachineFault(msg)
        a = self.ensure_dm_addr(self.sp - 1)
        return self.dm[a] & 0xFFFFFFFF

    def signal_read_mem(self, addr: int) -> int:
        a = self.ensure_dm_addr(addr)
        cu = self._cu_ref()
        if cu.superscalar:
            return self.read_from_dm_or_shadow(a)
        return self.dm[a] & 0xFFFFFFFF

    def signal_write_mem(self, addr: int, value: int, log: TextIO | None = None) -> None:
        a = self.ensure_dm_addr(addr)
        v = value & 0xFFFFFFFF
        cu = self._cu_ref()
        if cu.superscalar:
            if len(self.shadow_stores) >= _SHADOW_STORE_CAPACITY:
                self.flush_shadow_stores(log, reason="overflow")
            self.shadow_stores.append((a, v))
            self.shadow_busy_ticks = _SHADOW_STORE_TICKS
            self.note_store_visibility(a, v)
            return
        self.dm[a] = v

    def signal_read_port(self, port: int) -> int:
        if port == int(Port.DATA_IN):
            if self._irq_delivered_byte is not None:
                b = self._irq_delivered_byte & 0xFF
                self._irq_delivered_byte = None
                return b
            if self.input_queue:
                return self.input_queue.popleft() & 0xFF
            return -1
        return 0

    def signal_write_port(self, port: int, value: int) -> None:
        if port == int(Port.DATA_OUT):
            self.out_bytes.append(value & 0xFF)


class ControlUnit:
    """Блок управления: такт, выборка, фазы, IRQ, PC."""

    def __init__(
        self,
        dp: DataPath,
        *,
        im: list[int] | None = None,
        pc: int = 0,
        superscalar: bool = False,
        irq_schedule: tuple[IrqScheduleEvent, ...] = (),
        irq_pending: list[bool] | None = None,
        irq_line_value: list[int] | None = None,
        irq_enabled: bool = True,
    ) -> None:
        self.dp = dp
        self.dp._cu = self
        self.im: list[int] = im if im is not None else [0] * IM_SIZE_WORDS
        self.pc = pc
        self.ticks = 0
        self.halted = False
        self.superscalar = superscalar  # двойная выдача + deferred store
        self.pipeline: _InFlightInsn | None = None  # in-flight: незавершённая инструкция
        self.suspended_user_pipeline: _InFlightInsn | None = None  # сохранена при IRQ trap
        self.irq_schedule = irq_schedule  # внешние события trap по тактам
        self._schedule_i = 0  # индекс следующего события в irq_schedule
        self.irq_pending = (  # запрос по линии IRQ (не stdin)
            irq_pending if irq_pending is not None else [False] * NUM_IRQ_LINES
        )
        self.irq_line_value = (  # байт на линии при доставке trap
            irq_line_value if irq_line_value is not None else [0] * NUM_IRQ_LINES
        )
        self.irq_enabled = irq_enabled  # EI/CLI
        self.interrupt_depth = 0  # 0 = USR, >0 = внутри ISR

    def current_tick(self) -> int:
        return self.ticks

    def exec_mode(self) -> str:
        return "ISR" if self.interrupt_depth > 0 else "USR"

    def process_next_tick(self, log: TextIO | None = None) -> None:
        if self.halted:
            return

        self.ticks += 1
        if self.superscalar:
            self.dp.tick_shadow_background(log)
        self._apply_irq_schedule_for_current_ticks()
        if self._try_deliver_irq_before_issue(log):
            return
        self._step_execution(log)

    def ensure_im_pc(self, addr: int) -> int:
        if addr < 0 or addr >= IM_SIZE_WORDS:
            msg = f"PC {addr} вне IM"
            raise MachineFault(msg)
        return addr

    def _apply_irq_schedule_for_current_ticks(self) -> None:
        logical_tick = self.current_tick() - 1
        while self._schedule_i < len(self.irq_schedule):
            ev = self.irq_schedule[self._schedule_i]
            if ev.tick < logical_tick:
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
            raise MachineFault(msg)
        op_b, opnd = unpack_word(self.im[idx])
        if op_b != int(Opcode.JMP):
            msg = f"вектор IRQ{irq}: в IM[{idx}] должен быть jmp"
            raise MachineFault(msg)
        return self.ensure_im_pc(opnd & OPERAND_MASK)

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
        log.write(f"{self.ticks}\tFETCH\t{insn.pc}\t{insn.word:08X}\t{self.exec_mode()}\n")

    def _log_phase(
        self, insn: _InFlightInsn, phase: str, remaining: int, log: TextIO | None
    ) -> None:
        if log is None:
            return
        log.write(
            f"{self.ticks}\tPHASE\t{insn.phase_i}\t{phase}\t{remaining}\t{self.exec_mode()}\n",
        )

    def _advance_insn_phase(self, insn: _InFlightInsn, phase: str, log: TextIO | None) -> None:
        self._run_micro_phase(insn, phase, log)
        insn.phase_i += 1
        self._log_phase(insn, phase, insn.phases_remaining(), log)

    def _finish_insn_phases(self, insn: _InFlightInsn, log: TextIO | None) -> None:
        while insn.phases_remaining() > 0:
            phase = insn.phases[insn.phase_i]
            self._advance_insn_phase(insn, phase, log)

    def _issue_one(self, log: TextIO | None) -> None:
        insn = self._make_in_flight(self.ensure_im_pc(self.pc))
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
        insn = self.pipeline
        if insn is None or insn.phases_remaining() <= 0:
            self.pipeline = None
            return
        phase = insn.phases[insn.phase_i]
        self._advance_insn_phase(insn, phase, log)
        self.pipeline = insn if insn.phases_remaining() > 0 else None

    def _try_par_issue(self, log: TextIO | None) -> bool:
        pc0 = self.ensure_im_pc(self.pc)
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
        if _blocked_by_shadow_busy(op1, self.dp.shadow_busy_ticks):
            if log is not None:
                log.write(f"{self.ticks}\tPAR_BLOCK\tshadow_busy\t{self.exec_mode()}\n")
            return False

        if log is not None:
            log.write(
                f"{self.ticks}\tPAR\t{pc0}\t{word0:08X}\t{pc1}\t{word1:08X}\t{self.exec_mode()}\n",
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
        dp = self.dp
        op = insn.op_byte
        operand = insn.operand
        next_pc = insn.pc + 1

        if phase == "execute":
            if op == int(Opcode.ADD):
                x1 = dp.signal_pop()
                y = dp.signal_pop()
                insn.scratch["result"] = (y + x1) & 0xFFFFFFFF
                return
            if op == int(Opcode.SUB):
                x1 = dp.signal_pop()
                y = dp.signal_pop()
                insn.scratch["result"] = (y - x1) & 0xFFFFFFFF
                return
            if op == int(Opcode.EQ):
                x1 = dp.signal_pop() & 0xFFFFFFFF
                y = dp.signal_pop() & 0xFFFFFFFF
                insn.scratch["result"] = 1 if y == x1 else 0
                return
            if op == int(Opcode.SLT):
                b = dp.signal_pop() & 0xFFFFFFFF
                a = dp.signal_pop() & 0xFFFFFFFF
                insn.scratch["result"] = 1 if _signed32(a) < _signed32(b) else 0
                return
            if op == int(Opcode.RET):
                insn.scratch["ret_addr"] = self.ensure_im_pc(
                    dp.signal_pop() & 0xFFFFFFFF,
                )
                return
            if op == int(Opcode.IN):
                port = operand & 0xFFFF
                insn.scratch["in_val"] = _unsigned32(dp.signal_read_port(port))
                return
            if op == int(Opcode.OUT):
                insn.scratch["out_val"] = dp.signal_pop() & 0xFFFFFFFF
                insn.scratch["out_port"] = operand & 0xFFFF
                return
            if op == int(Opcode.LOAD):
                insn.scratch["addr"] = dp.ensure_dm_addr(dp.signal_pop())
                return
            if op == int(Opcode.STORE):
                insn.scratch["store_val"] = dp.signal_pop() & 0xFFFFFFFF
                return
            if op == int(Opcode.MUL):
                x1 = dp.signal_pop()
                y = dp.signal_pop()
                insn.scratch["mul_l"] = _signed32(y)
                insn.scratch["mul_r"] = _signed32(x1)
                return
            if op in (int(Opcode.DIV), int(Opcode.MOD)):
                x1 = dp.signal_pop()
                y = dp.signal_pop()
                if x1 == 0:
                    if op == int(Opcode.DIV):
                        raise MachineFault("деление на 0")
                    raise MachineFault("mod и делитель 0")
                insn.scratch["div_l"] = _signed32(y)
                insn.scratch["div_r"] = _signed32(x1)
                return
            if op == int(Opcode.JZ):
                cond = dp.signal_pop() & 0xFFFFFFFF
                insn.scratch["branch_taken"] = 1 if cond == 0 else 0
                insn.scratch["target_pc"] = self.ensure_im_pc(operand & OPERAND_MASK)
                return
            if op == int(Opcode.CALL):
                insn.scratch["target_pc"] = self.ensure_im_pc(operand & OPERAND_MASK)
                insn.scratch["ret_pc"] = next_pc & 0xFFFFFFFF
                return
            msg = f"execute-stage не поддерживает опкод 0x{op:02X}"
            raise MachineFault(msg)

        if phase == "memory":
            if op == int(Opcode.LOAD):
                a = insn.scratch["addr"]
                if (
                    self.superscalar
                    and dp.last_load_addr == a
                    and dp.last_load_value is not None
                ):
                    val = dp.last_load_value & 0xFFFFFFFF
                else:
                    val = dp.signal_read_mem(a)
                insn.scratch["load_val"] = val & 0xFFFFFFFF
                return
            if op == int(Opcode.STORE):
                insn.scratch["store_addr"] = dp.ensure_dm_addr(dp.signal_pop())
                return
            msg = f"memory-stage не поддерживает опкод 0x{op:02X}"
            raise MachineFault(msg)

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
            raise MachineFault(msg)

        if op == int(Opcode.NOP):
            self.pc = next_pc
            return
        if op == int(Opcode.HALT):
            if self.superscalar:
                dp.flush_shadow_stores(log, reason="halt")
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
            dp.signal_push(sign_extend_operand_i(operand) & 0xFFFFFFFF)
            self.pc = next_pc
            return
        if op == int(Opcode.DUP):
            dp.signal_push(dp.signal_peek_top())
            self.pc = next_pc
            return
        if op == int(Opcode.DROP):
            _ = dp.signal_pop()
            dp.invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.SWAP):
            top = dp.signal_pop()
            below = dp.signal_pop()
            dp.signal_push(top)
            dp.signal_push(below)
            dp.invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.JMP):
            self.pc = self.ensure_im_pc(operand & OPERAND_MASK)
            return
        if op == int(Opcode.ADD) or op == int(Opcode.SUB):
            dp.signal_push(insn.scratch["result"] & 0xFFFFFFFF)
            dp.invalidate_last_load()
            self.pc = next_pc
            return
        if op in (int(Opcode.EQ), int(Opcode.SLT)):
            dp.signal_push(insn.scratch["result"] & 0xFFFFFFFF)
            dp.invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.RET):
            self._complete_ret_writeback(insn)
            return
        if op == int(Opcode.IN):
            dp.signal_push(insn.scratch["in_val"] & 0xFFFFFFFF)
            dp.invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.OUT):
            dp.signal_write_port(insn.scratch["out_port"], insn.scratch["out_val"])
            dp.invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.LOAD):
            val = insn.scratch["load_val"] & 0xFFFFFFFF
            dp.signal_push(val)
            if self.superscalar:
                dp.last_load_addr = insn.scratch["addr"]
                dp.last_load_value = val
            self.pc = next_pc
            return
        if op == int(Opcode.STORE):
            a = insn.scratch["store_addr"]
            v = insn.scratch["store_val"] & 0xFFFFFFFF
            dp.signal_write_mem(a, v, log)
            self.pc = next_pc
            return
        if op in (int(Opcode.MUL), int(Opcode.DIV), int(Opcode.MOD)):
            dp.signal_push(insn.scratch["result"] & 0xFFFFFFFF)
            dp.invalidate_last_load()
            self.pc = next_pc
            return
        if op == int(Opcode.JZ):
            dp.invalidate_last_load()
            self.pc = insn.scratch["next_pc"]
            return
        if op == int(Opcode.CALL):
            dp.signal_push(insn.scratch["ret_pc"])
            dp.invalidate_last_load()
            self.pc = insn.scratch["target_pc"]
            return
        word = insn.word & 0xFFFFFFFF
        msg = f"writeback-stage не поддерживает опкод 0x{op:02X} @PC={insn.pc} word={word:08X}"
        raise MachineFault(msg)

    def _complete_ret_writeback(self, insn: _InFlightInsn) -> None:
        if self.interrupt_depth > 0:
            self.interrupt_depth -= 1
        self.dp.invalidate_last_load()
        self.pc = insn.scratch["ret_addr"]
        if self.interrupt_depth == 0 and self.suspended_user_pipeline:
            self.pipeline = self.suspended_user_pipeline
            self.suspended_user_pipeline = None

    def _try_deliver_irq_before_issue(self, log: TextIO | None = None) -> bool:
        if not self.irq_enabled:
            return False
        if self.interrupt_depth > 0:
            return False
        for irq in range(NUM_IRQ_LINES):
            if not self.irq_pending[irq]:
                continue
            if self.superscalar:
                self.dp.flush_shadow_stores(log, reason="irq")
            ret_pc = self.pc
            if self.pipeline is not None:
                self.suspended_user_pipeline = self.pipeline
                self.pipeline = None
            self.dp.signal_push(ret_pc & 0xFFFFFFFF)
            self.pc = self._read_vector_target(irq)
            self.interrupt_depth += 1
            self.dp._irq_delivered_byte = self.irq_line_value[irq] & 0xFF
            self.irq_pending[irq] = False
            if log is not None:
                log.write(f"{self.ticks}\tIRQ_TRAP\t{irq}\t{self.exec_mode()}\n")
            return True
        return False


class Machine:
    """Модель процессора: CU + DP"""

    def __init__(
        self,
        *,
        im: list[int] | None = None,
        dm: list[int] | None = None,
        pc: int = 0,
        sp: int = STACK_BASE,
        superscalar: bool = False,
        input_queue: deque[int] | None = None,
        irq_schedule: tuple[IrqScheduleEvent, ...] = (),
        irq_pending: list[bool] | None = None,
        irq_line_value: list[int] | None = None,
        irq_enabled: bool = True,
    ) -> None:
        self.data_path = DataPath(dm=dm, sp=sp, input_queue=input_queue)
        self.control_unit = ControlUnit(
            self.data_path,
            im=im,
            pc=pc,
            superscalar=superscalar,
            irq_schedule=irq_schedule,
            irq_pending=irq_pending,
            irq_line_value=irq_line_value,
            irq_enabled=irq_enabled,
        )

    @property
    def im(self) -> list[int]:
        return self.control_unit.im

    @property
    def dm(self) -> list[int]:
        return self.data_path.dm

    @property
    def pc(self) -> int:
        return self.control_unit.pc

    @pc.setter
    def pc(self, value: int) -> None:
        self.control_unit.pc = value

    @property
    def sp(self) -> int:
        return self.data_path.sp

    @property
    def ticks(self) -> int:
        return self.control_unit.ticks

    @property
    def halted(self) -> bool:
        return self.control_unit.halted

    @property
    def superscalar(self) -> bool:
        return self.control_unit.superscalar

    @property
    def pipeline(self) -> _InFlightInsn | None:
        return self.control_unit.pipeline

    @property
    def suspended_user_pipeline(self) -> _InFlightInsn | None:
        return self.control_unit.suspended_user_pipeline

    @property
    def input_queue(self) -> deque[int]:
        return self.data_path.input_queue

    @property
    def out_bytes(self) -> list[int]:
        return self.data_path.out_bytes

    @property
    def irq_schedule(self) -> tuple[IrqScheduleEvent, ...]:
        return self.control_unit.irq_schedule

    @property
    def irq_pending(self) -> list[bool]:
        return self.control_unit.irq_pending

    @property
    def irq_line_value(self) -> list[int]:
        return self.control_unit.irq_line_value

    @property
    def irq_enabled(self) -> bool:
        return self.control_unit.irq_enabled

    @property
    def interrupt_depth(self) -> int:
        return self.control_unit.interrupt_depth

    @property
    def shadow_stores(self) -> list[tuple[int, int]]:
        return self.data_path.shadow_stores

    @property
    def shadow_busy_ticks(self) -> int:
        return self.data_path.shadow_busy_ticks

    def step(self, log: TextIO | None = None) -> None:
        """Один тик модели через ControlUnit."""
        self.control_unit.process_next_tick(log)


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
            raise MachineFault(msg)
        im[i] = w & 0xFFFFFFFF
    for i, w in enumerate(data_words):
        if i >= DM_SIZE_WORDS:
            msg = "сегмент данных не влезает в DM"
            raise MachineFault(msg)
        dm[i] = w & 0xFFFFFFFF
    return im, dm


def run_program(
    machine: Machine,
    *,
    max_ticks: int,
    log: TextIO | None = None,
) -> None:
    """крутить step до halt/fault/лимита тактов"""
    while not machine.halted:
        if machine.ticks >= max_ticks:
            msg = f"лимит тактов ({max_ticks})"
            raise MachineFault(msg)
        machine.step(log=log)

