#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from golden_support import (  # noqa: E402
    GOLDEN_ROOT,
    IrqScheduleEvent,
    build_golden_document,
    write_golden_yml,
)

HELLO = """\
(defun emit-ch-at (base idx)
  (out (load (+ (+ base 1) idx))))

(defun emit-pstr-rec (base idx)
  (if (< idx (load base))
      (progn
        (emit-ch-at base idx)
        (emit-pstr-rec base (+ idx 1)))
      0))

(defun emit-pstr (base)
  (emit-pstr-rec base 0))

(emit-pstr "Hi\\n")
"""

CAT = """\
(progn
  (setq running 1)
  (ei)
  (loop (eq running 1) (nop)))

(interrupt 0
  (progn
    (setq c (in))
    (if (= c -1)
        (setq running 0)
        (out c))))
"""

HELLO_USER = """\
(defun emit-ch-at (base idx)
  (out (load (+ (+ base 1) idx))))

(defun emit-pstr-rec (base idx)
  (if (< idx (load base))
      (progn
        (emit-ch-at base idx)
        (emit-pstr-rec base (+ idx 1)))
      0))

(defun emit-pstr (base)
  (emit-pstr-rec base 0))

(progn
  (setq done 0)
  (setq name_len 0)
  (setq name_addr 100)
  (emit-pstr "What is your name?\\n")
  (ei)
  (loop (eq done 0) (nop))
  (store name_addr name_len)
  (emit-pstr "Hello, ")
  (emit-pstr name_addr)
  (emit-pstr "!\\n"))

(interrupt 0
  (progn
    (setq ch (in))
    (if (= ch 10)
        (setq done 1)
        (progn
          (store (+ name_addr (+ name_len 1)) ch)
          (setq name_len (+ name_len 1))))))
"""

SORT = """\
(progn
  (setq input_done 0)
  (setq got_n 0)
  (setq count 0)
  (setq n 0)
  (setq run 1)
  (setq swapped 0)
  (setq i 0)
  (setq k 0)
  (ei)
  (loop (eq input_done 0) (nop))
  (if (> n 1)
      (loop (eq run 1)
        (progn
          (setq swapped 0)
          (setq i 0)
          (loop (< (+ i 1) n)
            (progn
              (if (> (load (+ 128 i)) (load (+ 128 (+ i 1))))
                  (progn
                    (setq t (load (+ 128 i)))
                    (store (+ 128 i) (load (+ 128 (+ i 1))))
                    (store (+ 128 (+ i 1)) t)
                    (setq swapped 1))
                  0)
              (setq i (+ i 1))))
          (if (eq swapped 0) (setq run 0) 0)))
      0)
  (setq k 0)
  (loop (< k n)
    (progn
      (out (load (+ 128 k)))
      (setq k (+ k 1)))))

(interrupt 0
  (progn
    (setq ch (in))
    (if (= got_n 0)
        (progn (setq n ch) (setq got_n 1))
        (progn
          (store (+ 128 count) ch)
          (setq count (+ count 1))
          (if (= count n) (setq input_done 1) 0)))))
"""

DOUBLE_MATH = """\
(progn
  (setq a_hi 1)
  (setq a_lo -1)
  (setq b_hi 2)
  (setq b_lo 1)
  (setq sum_lo (+ a_lo b_lo))
  (setq carry (if (eq sum_lo 0) 1 0))
  (setq sum_hi (+ (+ a_hi b_hi) carry))
  (out (+ sum_lo 48))
  (out 32)
  (out (+ sum_hi 48))
  (out 10))
"""

CASES: dict[str, tuple[str, tuple[IrqScheduleEvent, ...]]] = {
    "hello": (HELLO, ()),
    "cat": (
        CAT,
        (
            IrqScheduleEvent(80, 0, ord("a")),
            IrqScheduleEvent(200, 0, ord("b")),
            IrqScheduleEvent(320, 0, ord("c")),
            IrqScheduleEvent(440, 0, eof=True),
        ),
    ),
    "hello_user_name": (
        HELLO_USER,
        (
            IrqScheduleEvent(800, 0, ord("A")),
            IrqScheduleEvent(920, 0, ord("l")),
            IrqScheduleEvent(1040, 0, ord("i")),
            IrqScheduleEvent(1160, 0, ord("c")),
            IrqScheduleEvent(1280, 0, ord("e")),
            IrqScheduleEvent(1400, 0, ord("\n")),
        ),
    ),
    "sort": (
        SORT,
        (
            IrqScheduleEvent(200, 0, 4),
            IrqScheduleEvent(400, 0, 4),
            IrqScheduleEvent(600, 0, 2),
            IrqScheduleEvent(800, 0, 5),
            IrqScheduleEvent(1000, 0, 1),
        ),
    ),
    "double_math": (DOUBLE_MATH, ()),
}


def _prob1_document() -> dict:
    from golden_support import capture_run, format_output, load_golden_yml  # noqa: E402

    path = GOLDEN_ROOT / "prob1.yml"
    doc = load_golden_yml(path)
    run = capture_run(
        str(doc["source"]),
        case="prob1",
        code_listing=str(doc["code_listing"]),
        data_listing=str(doc["data_listing"]),
        max_ticks=int(doc.get("max_ticks", 65_000_000)),
    )
    return {
        "name": "prob1",
        "source": doc["source"],
        "input": [],
        "max_ticks": int(doc.get("max_ticks", 65_000_000)),
        "fail_on_max_ticks": True,
        "output": format_output(run.output),
        "code_listing": doc["code_listing"],
        "data_listing": doc["data_listing"],
        "log_excerpt": run.log_excerpt,
    }


def main(argv: list[str]) -> int:
    names = argv[1:] if len(argv) > 1 else list(CASES.keys()) + ["prob1"]
    for name in names:
        print(f"regenerate {name}...", flush=True)
        if name == "prob1":
            doc = _prob1_document()
            out = GOLDEN_ROOT / f"{name}.yml"
            write_golden_yml(out, doc)
            print(f"  output={doc['output']!r}", flush=True)
            continue
        elif name in CASES:
            source, schedule = CASES[name]
        else:
            print(f"  skip unknown case {name}", flush=True)
            continue
        doc = build_golden_document(source, schedule=schedule, case=name)
        out = GOLDEN_ROOT / f"{name}.yml"
        write_golden_yml(out, doc)
        print(f"  output={doc['output']!r}", flush=True)
    print(f"done: {len(names)} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
