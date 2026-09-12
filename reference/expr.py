"""
最小表达式求值器 —— CEL 子集。

规范依据：spec/i4-action-minimal.md §2.3
    E-2  表达式语言 MUST 至少支持：比较运算、布尔组合、目标实例属性引用
    E-3  实现 SHOULD 使用 CEL

本实现是 **CEL 的一个受限子集**，不是完整 CEL。
覆盖 E-2 的三项 MUST 能力，另加 `+` 拼接（幂等键需要）。

支持：
    字面量        'str'  "str"  123  1.5  true  false  null
    路径          target.status        （属性引用）
    比较          ==  !=  <  <=  >  >=
    存在性        is null   is not null      ← 缺失可选参数的显式检查
    逻辑          and  &&   or  ||   not  !
    算术/拼接     +   -              （任一侧为 str 时做拼接）
    分组          ( ... )

**null 语义（I4 v0.2 §2.3 决定）**：
    · 缺失的可选参数绑定为 `null`
    · 与 `null` 的顺序比较（< <= > >=）返回"未知" → 前置条件判为**未通过**
    · `==` / `!=` 正常比较
    · 推荐用 `is null` / `is not null` 做**显式**存在性检查

不支持（会明确报错，不静默通过）：
    函数调用、集合运算、三元表达式、量词、字符串方法
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


class ExpressionError(Exception):
    """表达式非法或无法求值。"""


# --------------------------------------------------------------------------
# 词法
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    (?P<WS>\s+)
  | (?P<NUMBER>\d+\.\d+|\d+)
  | (?P<STRING>'[^']*'|"[^"]*")
  | (?P<OP><=|>=|==|!=|&&|\|\||[-+<>()!.])
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
""", re.VERBOSE)

KEYWORDS = {"and", "or", "not", "true", "false", "null", "is"}


@dataclass
class Token:
    kind: str          # NUMBER | STRING | OP | IDENT | KEYWORD
    value: Any
    pos: int


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(src):
        m = TOKEN_RE.match(src, i)
        if not m:
            raise ExpressionError(f"位置 {i}: 无法识别的字符 {src[i]!r}")
        i = m.end()
        kind = m.lastgroup
        text = m.group()
        if kind == "WS":
            continue
        if kind == "NUMBER":
            tokens.append(Token("NUMBER",
                                float(text) if "." in text else int(text),
                                m.start()))
        elif kind == "STRING":
            tokens.append(Token("STRING", text[1:-1], m.start()))
        elif kind == "OP":
            tokens.append(Token("OP", text, m.start()))
        elif kind == "IDENT":
            if text in KEYWORDS:
                tokens.append(Token("KEYWORD", text, m.start()))
            else:
                tokens.append(Token("IDENT", text, m.start()))
    tokens.append(Token("EOF", None, len(src)))
    return tokens


# --------------------------------------------------------------------------
# 语法（递归下降）
# --------------------------------------------------------------------------

class Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.toks[self.i]

    def next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept_op(self, *ops: str) -> str | None:
        t = self.peek()
        if t.kind == "OP" and t.value in ops:
            self.next()
            return t.value
        return None

    def accept_kw(self, *kws: str) -> str | None:
        t = self.peek()
        if t.kind == "KEYWORD" and t.value in kws:
            self.next()
            return t.value
        return None

    def expect_op(self, op: str) -> None:
        got = self.accept_op(op)
        if got is None:
            raise ExpressionError(
                f"位置 {self.peek().pos}: 期望 {op!r}，"
                f"实为 {self.peek().value!r}")

    # --- 产生式 ---

    def parse(self) -> Any:
        node = self.or_expr()
        if self.peek().kind != "EOF":
            raise ExpressionError(
                f"位置 {self.peek().pos}: 表达式结束后有多余内容 "
                f"{self.peek().value!r}")
        return node

    def or_expr(self) -> Any:
        node = self.and_expr()
        while self.accept_kw("or") or self.accept_op("||"):
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self) -> Any:
        node = self.not_expr()
        while self.accept_kw("and") or self.accept_op("&&"):
            node = ("and", node, self.not_expr())
        return node

    def not_expr(self) -> Any:
        if self.accept_kw("not") or self.accept_op("!"):
            return ("not", self.not_expr())
        return self.additive()

    def additive(self) -> Any:
        node = self.comparison()
        while True:
            op = self.accept_op("+", "-")
            if not op:
                break
            node = (op, node, self.comparison())
        return node

    def comparison(self) -> Any:
        node = self.primary()

        # `is null` / `is not null` —— 显式的存在性检查
        # 规范依据：I4 v0.2 §2.3 决定（缺失的可选参数绑定为 null，
        # 表达式 MUST 能用 is null 显式检查，否则一律判为未通过）
        if self.accept_kw("is"):
            negated = bool(self.accept_kw("not"))
            t = self.peek()
            if not (t.kind == "KEYWORD" and t.value == "null"):
                raise ExpressionError(
                    f"位置 {t.pos}: `is` 后面只能是 `null` 或 `not null`，"
                    f"实为 {t.value!r}")
            self.next()
            return ("isnull", node, negated)

        op = self.accept_op("==", "!=", "<=", ">=", "<", ">")
        if op:
            return ("cmp", op, node, self.primary())
        return node

    def primary(self) -> Any:
        t = self.peek()

        if t.kind == "NUMBER" or t.kind == "STRING":
            self.next()
            return ("lit", t.value)

        if t.kind == "KEYWORD" and t.value in ("true", "false", "null"):
            self.next()
            return ("lit", {"true": True, "false": False, "null": None}[t.value])

        if t.kind == "OP" and t.value == "-":
            self.next()
            return ("neg", self.primary())

        if t.kind == "OP" and t.value == "(":
            self.next()
            node = self.or_expr()
            self.expect_op(")")
            return node

        if t.kind == "IDENT":
            self.next()
            if self.peek().kind == "OP" and self.peek().value == "(":
                raise ExpressionError(
                    f"位置 {t.pos}: 不支持函数调用 `{t.value}(...)`。"
                    f"本实现是 CEL 子集，见模块文档")
            path = [t.value]
            while (self.peek().kind == "OP" and self.peek().value == "."):
                self.next()
                nxt = self.next()
                if nxt.kind != "IDENT":
                    raise ExpressionError(
                        f"位置 {nxt.pos}: `.` 后面必须是标识符")
                path.append(nxt.value)
            return ("path", path)

        raise ExpressionError(f"位置 {t.pos}: 无法解析 {t.value!r}")


# --------------------------------------------------------------------------
# 求值
# --------------------------------------------------------------------------

class Resolver:
    """
    路径解析器。

    子类覆盖 `resolve_root(name)`，返回根对象。
    根对象可以是：
      · 普通值
      · 带 `attr(name)` 方法的对象（如 TargetView）
      · dict（按键取值）
    """

    def resolve_root(self, name: str) -> Any:
        raise NotImplementedError

    def resolve_path(self, path: list[str]) -> Any:
        value = self.resolve_root(path[0])
        for segment in path[1:]:
            value = _attr(value, segment, path)
        return value


def _attr(obj: Any, name: str, path: list[str]) -> Any:
    if hasattr(obj, "attr"):
        return obj.attr(name)
    if isinstance(obj, dict):
        if name not in obj:
            return None
        return obj[name]
    raise ExpressionError(
        f"`{'.'.join(path)}`: `{name}` 之前的值不是可访问属性的对象")


class DictResolver(Resolver):
    """按名字查 dict；支持属性的 dict 可点访问。"""

    def __init__(self, context: dict[str, Any]):
        self.context = context

    def resolve_root(self, name: str) -> Any:
        if name not in self.context:
            raise ExpressionError(f"未定义的变量 `{name}`")
        return self.context[name]


def evaluate(node: Any, resolver: Resolver) -> Any:
    kind = node[0]

    if kind == "lit":
        return node[1]

    if kind == "path":
        return resolver.resolve_path(node[1])

    if kind == "neg":
        v = evaluate(node[1], resolver)
        if v is None:
            return None
        return -v

    if kind == "not":
        v = evaluate(node[1], resolver)
        if v is None:
            return None
        return not _truthy(v)

    if kind == "and":
        left = evaluate(node[1], resolver)
        if left is not None and not _truthy(left):
            return False                      # 短路
        right = evaluate(node[2], resolver)
        if left is None or right is None:
            return None
        return _truthy(left) and _truthy(right)

    if kind == "or":
        left = evaluate(node[1], resolver)
        if left is not None and _truthy(left):
            return True                       # 短路
        right = evaluate(node[2], resolver)
        if left is None or right is None:
            return None
        return _truthy(left) or _truthy(right)

    if kind == "+":
        a, b = evaluate(node[1], resolver), evaluate(node[2], resolver)
        if isinstance(a, str) or isinstance(b, str):
            return _as_text(a) + _as_text(b)
        return a + b

    if kind == "-":
        return evaluate(node[1], resolver) - evaluate(node[2], resolver)

    if kind == "isnull":
        v = evaluate(node[1], resolver)
        result = (v is None)
        return (not result) if node[2] else result

    if kind == "cmp":
        op = node[1]
        a, b = evaluate(node[2], resolver), evaluate(node[3], resolver)
        return _compare(op, a, b)

    raise ExpressionError(f"未知节点 {kind!r}")


def _truthy(v: Any) -> bool:
    return bool(v)


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _compare(op: str, a: Any, b: Any) -> Any:
    """
    比较语义（**本实现自定，规范未定义** —— 见 README『发现的规范缺口』）：

      · a 与 b 任一为 None 时：
          == / !=  按值比较（None == None 为真）
          其余     返回 None（"未知"，不是 False）
      · 类型不同且不可比时返回 None，不抛错
    """
    if a is None or b is None:
        if op == "==":
            return a is None and b is None
        if op == "!=":
            return not (a is None and b is None)
        return None

    if op == "==":
        return a == b
    if op == "!=":
        return a != b

    try:
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
    except TypeError:
        return None

    raise ExpressionError(f"未知比较运算符 {op!r}")


# --------------------------------------------------------------------------
# 对外门面
# --------------------------------------------------------------------------

_cache: dict[str, Any] = {}


def compile_expr(src: str) -> Any:
    """编译表达式为 AST（带缓存）。"""
    if src not in _cache:
        _cache[src] = Parser(tokenize(src)).parse()
    return _cache[src]


def eval_expr(src: str, context: dict[str, Any]) -> Any:
    """编译并求值。"""
    return evaluate(compile_expr(src), DictResolver(context))


def make_evaluator(default_vars: Callable[[], dict[str, Any]] | None = None):
    """
    构造一个可复用的求值函数。`default_vars` 每次调用时求值，
    保证 `NOW()` 之类的变量在一次提交内恒定（规范 E-4）。
    """
    def run(src: str, context: dict[str, Any]) -> Any:
        merged = dict(default_vars()) if default_vars else {}
        merged.update(context)
        return eval_expr(src, merged)
    return run
