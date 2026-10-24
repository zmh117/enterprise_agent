"""Bounded demo grammar, not a general business-semantic analyzer.

Tree-sitter reads executable expressions. A manually declared domain vocabulary
names this synthetic example; it supplies no thresholds, operators or outcomes.
Unknown wrappers, calls, macros or statements fail closed. No source is executed.
"""

import hashlib
import re
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_cpp
import tree_sitter_java
import tree_sitter_typescript


class AnalysisGap(Exception):
    """Safe error: never include source text or parser diagnostics."""


VOCABULARY = {
    "amountCents": ("订单金额（分）", "number"),
    "finance": ("具有财务审批身份", "boolean"),
    "quantity": ("订单数量", "number"),
    "approved": ("页面的已审批标记", "boolean"),
}
OPERATORS = {"<=": "不超过", ">=": "不少于", "<": "小于", ">": "大于", "==": "等于", "!=": "不等于"}
PROFILES = [
    {
        "file": "OrderPolicy.java",
        "id": "approval",
        "title": "订单审批资格",
        "language": "Java",
        "language_fn": tree_sitter_java.language,
        "envelope": "classOrderPolicy{staticbooleancanApprove(intamountCents,booleanfinance){return@;}}",
        "keys": {"amountCents", "finance"},
        "scope": "仅证明示例审批函数的返回条件；未验证生产入口、持久化或部署。",
        "outcome": "审批资格函数返回允许",
    },
    {
        "file": "quantity.cpp",
        "id": "quantity",
        "title": "订单数量范围",
        "language": "C++",
        "language_fn": tree_sitter_cpp.language,
        "envelope": "boolquantityAllowed(intquantity){return@;}",
        "keys": {"quantity"},
        "scope": "仅证明示例数量检查；未关联其他业务入口或编译目标。",
        "outcome": "数量检查返回通过",
    },
    {
        "file": "OrderForm.vue",
        "id": "submission",
        "title": "页面提交条件",
        "language": "Vue / TypeScript",
        "language_fn": tree_sitter_typescript.language_typescript,
        "envelope": "defineProps<{approved:boolean}>();functioncanSubmit(approved:boolean):boolean{return@;}",
        "keys": {"approved"},
        "scope": "只证明页面按钮可用条件，不代表后端授权或最终提交成功。",
        "outcome": "页面提交按钮可用",
    },
]


def walk(node):
    yield node
    for child in node.named_children:
        yield from walk(child)


def compact(text):
    return re.sub(r"\s+", "", text)


def expression(node, allowed):
    if node.type == "parenthesized_expression":
        return expression(node.named_children[0], allowed)
    token = node.text.decode()
    if node.type == "identifier" and token in allowed:
        label, kind = VOCABULARY[token]
        return {"kind": "input", "name": label, "type": kind}
    if node.type in {"decimal_integer_literal", "number_literal", "number"} and re.fullmatch(
        r"\d{1,9}", token
    ):
        return {"kind": "number", "value": int(token), "type": "number"}
    if token in {"true", "false"} and node.type in {"true", "false", "boolean_literal"}:
        return {"kind": "boolean", "value": token == "true", "type": "boolean"}
    if node.type == "binary_expression":
        left = expression(node.child_by_field_name("left"), allowed)
        right = expression(node.child_by_field_name("right"), allowed)
        op_node = node.child_by_field_name("operator")
        if op_node is None:
            raise AnalysisGap()
        op = op_node.text.decode()
        if op in {"&&", "||"}:
            valid = left["type"] == right["type"] == "boolean"
        else:
            valid = op in OPERATORS and left["type"] == right["type"] == "number"
        if valid:
            return {
                "kind": "binary",
                "operator": op,
                "left": left,
                "right": right,
                "type": "boolean",
            }
    raise AnalysisGap()


def describe(expr):
    if expr["kind"] == "input":
        return expr["name"]
    if expr["kind"] == "number":
        return str(expr["value"])
    if expr["kind"] == "boolean":
        return "始终满足" if expr["value"] else "始终不满足"
    op = expr["operator"]
    left, right = describe(expr["left"]), describe(expr["right"])
    if op in {"&&", "||"}:
        return f"（{left}）{'并且' if op == '&&' else '或者'}（{right}）"
    return f"{left}{OPERATORS[op]}{right}"


def evaluate(expr, inputs):
    if expr["kind"] == "input":
        return inputs[expr["name"]]
    if expr["kind"] in {"number", "boolean"}:
        return expr["value"]
    a, b = evaluate(expr["left"], inputs), evaluate(expr["right"], inputs)
    return {
        "&&": lambda: a and b,
        "||": lambda: a or b,
        "<=": lambda: a <= b,
        ">=": lambda: a >= b,
        "<": lambda: a < b,
        ">": lambda: a > b,
        "==": lambda: a == b,
        "!=": lambda: a != b,
    }[expr["operator"]]()


def parse_rule(source, profile):
    if len(source) > 16000:
        raise AnalysisGap()
    if profile["id"] == "submission":
        # Deliberately supports only this exact, single-script SFC envelope.
        match = re.fullmatch(
            r'\s*<script setup lang="ts">(.*?)</script>\s*<template>\s*'
            r'<button :disabled="!canSubmit\(approved\)">提交订单</button>\s*'
            r"</template>\s*",
            source,
            re.S,
        )
        if not match:
            raise AnalysisGap()
        source = match[1]
    data = source.encode()
    tree = Parser(Language(profile["language_fn"]())).parse(data)
    nodes = list(walk(tree.root_node))
    if tree.root_node.has_error or len(nodes) > 500:
        raise AnalysisGap()
    returns = [node for node in nodes if node.type == "return_statement"]
    if len(returns) != 1 or len(returns[0].named_children) != 1:
        raise AnalysisGap()
    expr_node = returns[0].named_children[0]
    # Only the expression may change. Strip grammar-recognized comments, not regex guesses.
    replacements = [(expr_node.start_byte, expr_node.end_byte, b"@")]
    replacements += [
        (n.start_byte, n.end_byte, b"")
        for n in nodes
        if "comment" in n.type and not (expr_node.start_byte <= n.start_byte < expr_node.end_byte)
    ]
    envelope = data
    for start, end, value in sorted(replacements, reverse=True):
        envelope = envelope[:start] + value + envelope[end:]
    if compact(envelope.decode()) != profile["envelope"]:
        raise AnalysisGap()
    expr = expression(expr_node, profile["keys"])
    if expr["type"] != "boolean":
        raise AnalysisGap()
    fact = {
        "id": profile["id"],
        "title": profile["title"],
        "language": profile["language"],
        "rule": f"当且仅当{describe(expr)}时，{profile['outcome']}。",
        "scope": profile["scope"],
        "condition": expr,
        "coverage": "限定样例已核验",
    }
    examples = {
        "approval": [
            ({"订单金额（分）": 80000, "具有财务审批身份": False}, "800 元、无财务身份"),
            ({"订单金额（分）": 120000, "具有财务审批身份": False}, "1200 元、无财务身份"),
            ({"订单金额（分）": 120000, "具有财务审批身份": True}, "1200 元、有财务身份"),
        ],
        "quantity": [({"订单数量": n}, f"数量 {n}") for n in (0, 30, 80, 101)],
        "submission": [
            ({"页面的已审批标记": b}, "页面已审批" if b else "页面未审批") for b in (False, True)
        ],
    }
    fact["examples"] = [
        {"input": label, "result": "通过" if evaluate(expr, values) else "不通过"}
        for values, label in examples[profile["id"]]
    ]
    return fact


def parse_schema(source):
    match = re.fullmatch(r"\s*CREATE TABLE (orders)\s*\((.*?)\);\s*", source, re.S)
    if not match:
        raise AnalysisGap()
    fields = []
    for definition in match[2].split(","):
        field = re.fullmatch(
            r"\s*(id|amount_cents|quantity|approved)\s+(INTEGER|BOOLEAN)\s+(PRIMARY KEY|NOT NULL)\s*",
            definition,
        )
        if not field:
            raise AnalysisGap()
        name, kind, constraint = field.groups()
        fields.append({"name": name, "type": kind, "constraint": constraint})
    if len(fields) != 4 or len({f["name"] for f in fields}) != 4:
        raise AnalysisGap()
    return {
        "id": "schema",
        "title": "订单表结构",
        "language": "DDL",
        "rule": "代码定义 orders 表；字段与约束如下。",
        "table": "orders",
        "fields": fields,
        "scope": "仅为样例 DDL 定义，未连接生产数据库，未证明字段和三个函数之间的持久化映射。",
        "coverage": "限定样例已核验",
        "examples": [],
    }


def analyze(directory: Path):
    expected = {p["file"] for p in PROFILES} | {"schema.sql"}
    actual = {p.name for p in directory.iterdir()}
    if actual != expected or any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
        raise AnalysisGap()
    facts, evidence = [], []
    for profile in PROFILES:
        source = (directory / profile["file"]).read_text()
        facts.append(parse_rule(source, profile))
        evidence.append(
            {
                "topic": profile["id"],
                "file": profile["file"],
                "sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
        )
    schema = (directory / "schema.sql").read_text()
    facts.append(parse_schema(schema))
    evidence.append(
        {
            "topic": "schema",
            "file": "schema.sql",
            "sha256": hashlib.sha256(schema.encode()).hexdigest(),
        }
    )
    return facts, evidence
